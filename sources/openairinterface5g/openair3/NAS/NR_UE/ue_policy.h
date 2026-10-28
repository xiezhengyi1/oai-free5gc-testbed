/* SPDX-License-Identifier: LicenseRef-CSSL-1.0 */
#ifndef OAI_UE_POLICY_H
#define OAI_UE_POLICY_H
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define UE_POLICY_MAX_RULES 32
#define UE_POLICY_MAX_ROUTES 8
typedef struct {
  uint8_t precedence, sst;
  uint32_t sd;
  char dnn[101];
} ue_policy_route_t;
typedef struct {
  uint8_t precedence, protocol;
  uint16_t port;
  uint32_t address, mask;
  size_t route_count;
  ue_policy_route_t routes[UE_POLICY_MAX_ROUTES];
} ue_policy_rule_t;
typedef struct {
  uint8_t pti, plmn[3];
  uint16_t upsc;
  size_t rule_count;
  ue_policy_rule_t rules[UE_POLICY_MAX_RULES];
} ue_policy_t;

/* All cursor checks enforce the external NAS wire boundary. */
int ue_policy_decode(const uint8_t *data, size_t size, ue_policy_t *out);
const ue_policy_rule_t *ue_policy_match(const ue_policy_t *policy, uint32_t ipv4, uint8_t protocol, uint16_t port);
int ue_policy_save(const char *path, const uint8_t *data, size_t size);
int ue_policy_load(const char *path, ue_policy_t *out);
size_t ue_policy_result(const ue_policy_t *policy, bool accepted, uint8_t out[13]);
#endif
