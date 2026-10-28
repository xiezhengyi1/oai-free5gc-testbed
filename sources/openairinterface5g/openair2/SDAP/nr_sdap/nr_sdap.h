/*
 * SPDX-License-Identifier: LicenseRef-CSSL-1.0
 */

#ifndef _NR_SDAP_GNB_H_
#define _NR_SDAP_GNB_H_

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include "common/platform_types.h"

struct nr_sdap_entity_s;

#define NR_SDAP_MAX_QOS_RULES 64
#define NR_SDAP_MAX_PACKET_FILTERS 15

typedef struct nr_sdap_qos_packet_filter_s {
  uint8_t id;
  uint8_t direction;
  bool match_all;
  bool has_local_ipv4;
  uint8_t local_ipv4[4];
  uint8_t local_ipv4_mask[4];
  bool has_remote_ipv4;
  uint8_t remote_ipv4[4];
  uint8_t remote_ipv4_mask[4];
  bool has_protocol;
  uint8_t protocol;
  bool has_local_ports;
  uint16_t local_port_low;
  uint16_t local_port_high;
  bool has_remote_ports;
  uint16_t remote_port_low;
  uint16_t remote_port_high;
} nr_sdap_qos_packet_filter_t;

typedef struct nr_sdap_qos_rule_s {
  bool active;
  uint8_t id;
  uint8_t operation;
  uint8_t precedence;
  uint8_t qfi;
  uint8_t packet_filter_count;
  nr_sdap_qos_packet_filter_t packet_filters[NR_SDAP_MAX_PACKET_FILTERS];
} nr_sdap_qos_rule_t;

/*
 * TS 37.324 4.4 Functions
 * Transfer of user plane data
 * Downlink - gNB
 * Uplink   - nrUE
 */
bool sdap_data_req(protocol_ctxt_t *ctxt_p,
                   const ue_id_t ue_id,
                   const srb_flag_t srb_flag,
                   const mui_t mui,
                   const confirm_t confirm,
                   const sdu_size_t sdu_buffer_size,
                   unsigned char *const sdu_buffer,
                   const pdcp_transmission_mode_t pt_mode,
                   const uint32_t *sourceL2Id,
                   const uint32_t *destinationL2Id,
                   const uint8_t qfi,
                   const bool rqi,
                   const int pdusession_id);

/*
 * TS 37.324 4.4 Functions
 * Transfer of user plane data
 * Uplink   - gNB
 * Downlink - nrUE
 */
void sdap_data_ind(int drb_id, int is_gnb, int pdusession_id, ue_id_t ue_id, char *buf, int size);

void start_sdap_tun_gnb_first_ue_default_pdu_session(ue_id_t ue_id, int pdu_session_id);
void create_ue_ip_if(const char *ipv4, const char *ipv6, int ue_id, int pdu_session_id, bool is_default);
void create_ue_eth_if(int ue_id, int pdu_session_id, bool is_default);
void nr_sdap_tun_attach(struct nr_sdap_entity_s *entity);
void nr_sdap_tun_detach(struct nr_sdap_entity_s *entity);
void nr_sdap_tun_destroy(ue_id_t ue_id, int pdusession_id);
void nr_sdap_tun_store_qfi(ue_id_t ue_id, int pdusession_id, uint8_t qfi);
int nr_sdap_tun_apply_qos_rules(
    ue_id_t ue_id,
    int pdusession_id,
    const nr_sdap_qos_rule_t *updates,
    size_t update_count);

#endif
