/*
 * SPDX-License-Identifier: LicenseRef-CSSL-1.0
 */

#include <netinet/in.h>
#include <arpa/inet.h>
#include <string.h>
#include "PduSessionEstablishmentAccept.h"
#include "common/utils/LOG/log.h"
#include "common/utils/utils.h" // text_info_t, TO_ENUM, TO_TEXT
#include "fgs_nas_utils.h"

static int decode_packet_filter(packet_filter_t *filter, const uint8_t **cursor, const uint8_t *end)
{
  if (end - *cursor < 2)
    return -1;
  filter->direction = (**cursor & 0x30) >> 4;
  filter->id = *(*cursor)++ & 0x0f;
  uint8_t length = *(*cursor)++;
  if (end - *cursor < length)
    return -1;
  const uint8_t *filter_end = *cursor + length;
  while (*cursor < filter_end) {
    uint8_t type = *(*cursor)++;
    switch (type) {
      case 0x01:
        filter->match_all = true;
        break;
      case 0x10:
        if (filter_end - *cursor < 8) return -1;
        filter->has_remote_ipv4 = true;
        memcpy(filter->remote_ipv4, *cursor, 4);
        memcpy(filter->remote_ipv4_mask, *cursor + 4, 4);
        *cursor += 8;
        break;
      case 0x11:
        if (filter_end - *cursor < 8) return -1;
        filter->has_local_ipv4 = true;
        memcpy(filter->local_ipv4, *cursor, 4);
        memcpy(filter->local_ipv4_mask, *cursor + 4, 4);
        *cursor += 8;
        break;
      case 0x30:
        if (filter_end - *cursor < 1) return -1;
        filter->has_protocol = true;
        filter->protocol = *(*cursor)++;
        break;
      case 0x40:
      case 0x50: {
        if (filter_end - *cursor < 2) return -1;
        uint16_t port = 0;
        GET_SHORT(*cursor, port);
        *cursor += 2;
        if (type == 0x40) {
          filter->has_local_ports = true;
          filter->local_port_low = filter->local_port_high = port;
        } else {
          filter->has_remote_ports = true;
          filter->remote_port_low = filter->remote_port_high = port;
        }
        break;
      }
      case 0x41:
      case 0x51: {
        if (filter_end - *cursor < 4) return -1;
        uint16_t low = 0;
        uint16_t high = 0;
        GET_SHORT(*cursor, low);
        GET_SHORT(*cursor + 2, high);
        *cursor += 4;
        if (type == 0x41) {
          filter->has_local_ports = true;
          filter->local_port_low = low;
          filter->local_port_high = high;
        } else {
          filter->has_remote_ports = true;
          filter->remote_port_low = low;
          filter->remote_port_high = high;
        }
        break;
      }
      default:
        return -1;
    }
  }
  return *cursor == filter_end ? 0 : -1;
}

int decode_authorized_qos_rules(auth_qos_rule_t *rules, const uint8_t *buffer, uint32_t length)
{
  memset(rules, 0, sizeof(*rules));
  rules->length = length;
  const uint8_t *cursor = buffer;
  const uint8_t *end = buffer + length;
  while (cursor < end) {
    if (rules->rule_count == MAX_NUM_QOS_RULES || end - cursor < 4)
      return -1;
    qos_rule_t *rule = &rules->rule[rules->rule_count];
    rule->id = *cursor++;
    GET_SHORT(cursor, rule->length);
    cursor += 2;
    if (end - cursor < rule->length || rule->length < 3)
      return -1;
    const uint8_t *rule_end = cursor + rule->length;
    rule->oc = (*cursor & 0xe0) >> 5;
    rule->dqr = (*cursor & 0x10) >> 4;
    rule->nb_pf = *cursor++ & 0x0f;
    if (rule->oc == ROC_RESERVED_0 || rule->oc == ROC_RESERVED_1)
      return -1;
    if (rule->oc == ROC_MODIFY_QOS_RULE_DELETE_PF) {
      if (rule_end - cursor < rule->nb_pf + 2)
        return -1;
      for (int i = 0; i < rule->nb_pf; ++i)
        rule->packet_filters[i].id = *cursor++ & 0x0f;
    } else {
      for (int i = 0; i < rule->nb_pf; ++i) {
        if (decode_packet_filter(&rule->packet_filters[i], &cursor, rule_end) != 0)
          return -1;
      }
    }
    if (rule_end - cursor != 2)
      return -1;
    rule->precendence = *cursor++;
    rule->qfi = *cursor++ & 0x3f;
    rules->rule_count++;
  }
  return cursor == end ? (int)length : -1;
}

/**
 * @brief PDU session establishment accept (8.3.2 of 3GPP TS 24.501)
 *        network to UE
 */
int decode_pdu_session_establishment_accept_msg(pdu_session_establishment_accept_msg_t *psea_msg, uint8_t *buffer, uint32_t msg_length)
{
  uint8_t *curPtr = buffer;

  /* Mandatory PDU Session Establishment Accept IEs */
  // PDU Session Type (half octet)
  psea_msg->pdu_type = *curPtr & 0x0f;
  // SSC Mode (half octet)
  psea_msg->ssc_mode = (*curPtr++ & 0xf0) >> 4;
  // Authorized QoS Rules
  auth_qos_rule_t *qos_rules = &psea_msg->qos_rules;
  // Length of the rule IEs (2 octets)
  GET_SHORT(curPtr, qos_rules->length);
  curPtr += sizeof(qos_rules->length);
  /* Decode rule IEs as long as the total length
    of all IEs (qos_rules->length) is not reached */
  if (decode_authorized_qos_rules(qos_rules, curPtr, qos_rules->length) < 0)
    return 0;
  curPtr += qos_rules->length;
  // Session-AMBR (M)
  psea_msg->sess_ambr.length = *curPtr++;
  curPtr += psea_msg->sess_ambr.length; // skip content

  uint8_t *resPtr = curPtr;

  /* Optional Presence IEs */
  while (curPtr < buffer + msg_length) {
    uint8_t psea_iei = *curPtr++;
    LOG_T(NAS, "PDU SESSION ESTABLISHMENT ACCEPT - Received %s IEI\n", iei_text_desc[psea_iei].text);
    switch (psea_iei) {
      case IEI_5GSM_CAUSE: /* Ommited */
        curPtr++;
        break;

      case IEI_PDU_ADDRESS:
        psea_msg->pdu_addr_ie.pdu_length = *curPtr++;

        /* Octet 3 */
        // PDU type (3 bits)
        psea_msg->pdu_addr_ie.pdu_type = *curPtr & 0x07;
        // SMF's IPv6 link local address (1 bit)
        uint8_t si6lla = (*curPtr >> 3) & 0x01;
        if (si6lla)
          LOG_E(NAS, "SMF's IPv6 link local address is not handled\n");
        curPtr++;

        /* Octet 4 to n */
        // PDU address information
        uint8_t *addr = psea_msg->pdu_addr_ie.pdu_addr_oct;
        if (psea_msg->pdu_addr_ie.pdu_type == PDU_SESSION_TYPE_IPV4) {
          for (int i = 0; i < IPv4_ADDRESS_LENGTH; ++i)
            addr[i] = *curPtr++;
          LOG_I(NAS, "Received PDU Session Establishment Accept, UE IPv4: %u.%u.%u.%u\n", addr[0], addr[1], addr[2], addr[3]);
        } else if (psea_msg->pdu_addr_ie.pdu_type == PDU_SESSION_TYPE_IPV6) {
          for (int i = 0; i < IPv6_INTERFACE_ID_LENGTH; ++i)
            addr[i] = *curPtr++;
          LOG_I(NAS, "Received PDU Session Establishment Accept, UE IPv6: %u.%u.%u.%u.%u.%u.%u.%u\n",
                addr[0], addr[1], addr[2], addr[3], addr[4], addr[5], addr[6], addr[7]);
        } else if (psea_msg->pdu_addr_ie.pdu_type == PDU_SESSION_TYPE_IPV4V6) {
          // 24.501 Sec 9.11.4.10: "If the PDU session type value indicates
          // IPv4v6, the PDU address information in octet 4 to octet 11
          // contains an interface identifier for the IPv6 link local address
          // and in octet 12 to octet 15 contains an IPv4 address."
          for (int i = 0; i < IPv4_ADDRESS_LENGTH + IPv6_INTERFACE_ID_LENGTH; ++i)
            addr[i] = *curPtr++;
          LOG_I(NAS, "Received PDU Session Establishment Accept, UE IPv4v6: %u.%u.%u.%u/%u.%u.%u.%u.%u.%u.%u.%u\n",
                addr[8], addr[9], addr[10], addr[11],
                addr[0], addr[1], addr[2], addr[3], addr[4], addr[5], addr[6], addr[7]);
        } else {
          LOG_E(NAS, "unknown/unhandled PDU session establishment accept PDU type %d\n", psea_msg->pdu_addr_ie.pdu_type);
          curPtr += psea_msg->pdu_addr_ie.pdu_length;
        }
        break;

      case IEI_RQ_TIMER_VALUE: /* Ommited */
        curPtr++; /* TS 24.008 10.5.7.3 */
        break;

      case IEI_SNSSAI: {
        uint8_t snssai_length = *curPtr;
        curPtr += (snssai_length + sizeof(snssai_length));
        break;
      }

      case IEI_ALWAYSON_PDU: /* Ommited */
        curPtr++;
        break;

      case IEI_MAPPED_EPS: {
        uint16_t mapped_eps_length = 0;
        GET_SHORT(curPtr, mapped_eps_length);
        curPtr += mapped_eps_length;
        break;
      }

      case IEI_EAP_MSG: {
        uint16_t eap_length = 0;
        GET_SHORT(curPtr, eap_length);
        curPtr += (eap_length + sizeof(eap_length));
        break;
      }

      case IEI_AUTH_QOS_DESC: {
        GET_SHORT(curPtr, psea_msg->qos_fd_ie.length);
        curPtr += (psea_msg->qos_fd_ie.length + sizeof(psea_msg->qos_fd_ie.length));
        break;
      }

      case IEI_EXT_CONF_OPT: {
        GET_SHORT(curPtr, psea_msg->ext_pp_ie.length);
        curPtr += (psea_msg->ext_pp_ie.length + sizeof(psea_msg->ext_pp_ie.length));
        break;
      }

      case IEI_DNN: {
        psea_msg->dnn_ie.dnn_length = *curPtr++;
        char apn[APN_MAX_LEN];

        if (psea_msg->dnn_ie.dnn_length <= APN_MAX_LEN && psea_msg->dnn_ie.dnn_length >= APN_MIN_LEN) {
          memcpy(apn, curPtr, psea_msg->dnn_ie.dnn_length);
          LOG_T(NAS, "PDU SESSION ESTABLISHMENT ACCEPT - APN: %s\n", apn);
        } else
          LOG_E(NAS, "PDU SESSION ESTABLISHMENT ACCEPT - DNN IE has invalid length\n");
        resPtr = curPtr;
        curPtr = buffer + msg_length; // we force stop processing
        break;
      }

      default:
        PRINT_ERROR("Unknown IEI %d\n", psea_iei);
        curPtr = buffer + msg_length; // we force stop processing
        break;
    }
  }
  return resPtr - buffer;
}
