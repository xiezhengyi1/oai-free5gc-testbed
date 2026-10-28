/* SPDX-License-Identifier: LicenseRef-CSSL-1.0 */
#include "ue_policy.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>

int main(int argc,char **argv)
{
  assert(argc==2);
  FILE *file=fopen(argv[1],"rb"); assert(file);
  uint8_t bytes[65536]; size_t n=fread(bytes,1,sizeof(bytes),file); fclose(file);
  ue_policy_t policy;
  assert(ue_policy_decode(bytes,n,&policy)==0);
  assert(policy.rule_count==1 && policy.upsc==1 && policy.pti==1);
  const ue_policy_rule_t *rule=ue_policy_match(&policy,0x01020304,17,5000);
  assert(rule && !strcmp(rule->routes[0].dnn,"internet") && rule->routes[0].sd==0x010203);
  uint8_t result[13]; assert(ue_policy_result(&policy,true,result)==2 && result[1]==2);
  assert(ue_policy_result(&policy,false,result)==13 && result[12]==0x6f);
  for (size_t i=0;i<n;i++) assert(ue_policy_decode(bytes,i,&policy)!=0);
  for (size_t i=0;i<n;i++) {
    for (unsigned bit=1;bit<256;bit<<=1) {
      bytes[i]^=bit; ue_policy_decode(bytes,n,&policy); bytes[i]^=bit;
    }
  }
  bytes[0]=0; assert(ue_policy_decode(bytes,n,&policy)!=0);
  puts("UE policy wire decoder, classifier, result and truncation tests passed");
}
