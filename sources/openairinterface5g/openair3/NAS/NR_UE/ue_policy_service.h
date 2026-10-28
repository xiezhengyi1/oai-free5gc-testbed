/* SPDX-License-Identifier: LicenseRef-CSSL-1.0 */
#ifndef UE_POLICY_SERVICE_H
#define UE_POLICY_SERVICE_H
#include "nr_nas_msg.h"
void ue_policy_service_start(nr_ue_nas_t *nas);
/* Caller holds ue_policy_lock. */
void ue_policy_write_state(nr_ue_nas_t *nas);
#endif
