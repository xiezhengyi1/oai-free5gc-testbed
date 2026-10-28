/* SPDX-License-Identifier: LicenseRef-CSSL-1.0 */
#include "ue_policy.h"
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

typedef struct { const uint8_t *p; size_t n; } cursor_t;
static int take(cursor_t *c, size_t n, cursor_t *out)
{
  if (n > c->n) return -1;
  *out = (cursor_t){c->p,n}; c->p += n; c->n -= n; return 0;
}
static int u8(cursor_t *c, uint8_t *out)
{
  if (!c->n) return -1;
  *out = *c->p++; --c->n; return 0;
}
static int u16(cursor_t *c, uint16_t *out)
{
  if (c->n < 2) return -1;
  *out = ((uint16_t)c->p[0] << 8) | c->p[1]; c->p += 2; c->n -= 2; return 0;
}
static int lv(cursor_t *c, cursor_t *out)
{
  uint16_t n; return u16(c,&n) || take(c,n,out) ? -1 : 0;
}
static uint32_t be32(const uint8_t *p)
{
  return (uint32_t)p[0]<<24 | (uint32_t)p[1]<<16 | (uint32_t)p[2]<<8 | p[3];
}
static int decode_dnn(cursor_t c, char out[101])
{
  size_t used=0;
  while (c.n) {
    uint8_t n; cursor_t label;
    if (u8(&c,&n) || !n || n>63 || take(&c,n,&label) || used+n+(used!=0)>100) return -1;
    if (used) out[used++]='.';
    for (size_t i=0;i<n;i++) {
      uint8_t ch=label.p[i];
      if (!((ch>='a'&&ch<='z') || (ch>='0'&&ch<='9') || ch=='-')) return -1;
      out[used++]=ch;
    }
  }
  out[used]=0; return used ? 0 : -1;
}
static int decode_route(cursor_t c, ue_policy_route_t *route)
{
  cursor_t contents;
  route->sd=0xffffff;
  if (u8(&c,&route->precedence) || lv(&c,&contents) || c.n) return -1;
  bool got_slice=false,got_dnn=false;
  while (contents.n) {
    uint8_t type,n; cursor_t value;
    if (u8(&contents,&type) || u8(&contents,&n) || take(&contents,n,&value)) return -1;
    if (type==2) {
      if (got_slice || (n!=1 && n!=4)) return -1;
      got_slice=true; route->sst=value.p[0];
      if (n==4) route->sd=(uint32_t)value.p[1]<<16 | (uint32_t)value.p[2]<<8 | value.p[3];
    } else if (type==4) {
      if (got_dnn || decode_dnn(value,route->dnn)) return -1;
      got_dnn=true;
    } else { return -1; }
  }
  return got_slice && got_dnn ? 0 : -1;
}
static int decode_rule(cursor_t c, ue_policy_rule_t *rule)
{
  cursor_t td,rsds;
  if (u8(&c,&rule->precedence) || lv(&c,&td) || !td.n || lv(&c,&rsds) || c.n) return -1;
  unsigned fields=0;
  while (td.n) {
    uint8_t type; cursor_t value;
    if (u8(&td,&type)) return -1;
    switch (type) {
      case 1: if (fields || td.n) return -1; fields=1; break;
      case 0x10:
        if ((fields&3) || take(&td,8,&value)) return -1;
        fields|=2; rule->address=be32(value.p); rule->mask=be32(value.p+4); break;
      case 0x30:
        if ((fields&5) || u8(&td,&rule->protocol)) return -1;
        fields|=4; break;
      case 0x50:
        if ((fields&9) || u16(&td,&rule->port)) return -1;
        fields|=8; break;
      default: return -1;
    }
  }
  while (rsds.n) {
    cursor_t rsd;
    if (rule->route_count==UE_POLICY_MAX_ROUTES || lv(&rsds,&rsd)) return -1;
    ue_policy_route_t *route=&rule->routes[rule->route_count++];
    if (decode_route(rsd,route)) return -1;
    for (size_t j=0;j+1<rule->route_count;j++)
      if (rule->routes[j].precedence==route->precedence) return -1;
  }
  return rule->route_count ? 0 : -1;
}
int ue_policy_decode(const uint8_t *data, size_t size, ue_policy_t *out)
{
  ue_policy_t policy={0};
  cursor_t c={data,size},list,sublist,plmn,instruction,rules;
  uint8_t type; uint16_t part_length;
  if (u8(&c,&policy.pti) || !policy.pti || policy.pti==255 || u8(&c,&type) || type!=1 || lv(&c,&list)) return -1;
  /* Profile: one PLMN / one policy section / one URSP part, up to 32 rules. */
  if (lv(&list,&sublist) || list.n || take(&sublist,3,&plmn) || lv(&sublist,&instruction) || sublist.n || u16(&instruction,&policy.upsc)) return -1;
  memcpy(policy.plmn,plmn.p,3);
  if (!instruction.n) { *out=policy; return 0; } /* Delete section. */
  if (u16(&instruction,&part_length) || !part_length || u8(&instruction,&type) || type!=1 || take(&instruction,part_length-1,&rules) || instruction.n) return -1;
  while (rules.n) {
    cursor_t rule;
    if (policy.rule_count==UE_POLICY_MAX_RULES || lv(&rules,&rule)) return -1;
    ue_policy_rule_t *decoded=&policy.rules[policy.rule_count++];
    if (decode_rule(rule,decoded)) return -1;
    for (size_t j=0;j+1<policy.rule_count;j++)
      if (policy.rules[j].precedence==decoded->precedence) return -1;
  }
  if (!policy.rule_count) return -1;
  *out=policy; return 0;
}
const ue_policy_rule_t *ue_policy_match(const ue_policy_t *policy,uint32_t ipv4,uint8_t protocol,uint16_t port)
{
  const ue_policy_rule_t *best=NULL;
  for (size_t i=0;i<policy->rule_count;i++) {
    const ue_policy_rule_t *r=&policy->rules[i];
    if ((ipv4&r->mask)!=(r->address&r->mask) || (r->protocol && r->protocol!=protocol) || (r->port && r->port!=port)) continue;
    if (!best || r->precedence<best->precedence) best=r;
  }
  return best;
}
int ue_policy_save(const char *path,const uint8_t *data,size_t size)
{
  char temp[4096];
  if (snprintf(temp,sizeof(temp),"%s.tmp",path)>=(int)sizeof(temp)) return -1;
  FILE *f=fopen(temp,"wb");
  if (!f) return -1;
  int status=fwrite(data,1,size,f)==size && fflush(f)==0 && fsync(fileno(f))==0 ? 0 : -1;
  if (fclose(f)!=0) status=-1;
  if (status==0) status=rename(temp,path);
  if (status!=0) unlink(temp);
  return status;
}
int ue_policy_load(const char *path,ue_policy_t *out)
{
  FILE *f=fopen(path,"rb");
  if (!f) return errno==ENOENT ? 1 : -1;
  uint8_t data[65536]; size_t n=fread(data,1,sizeof(data),f);
  int status=ferror(f) || n==sizeof(data) ? -1 : ue_policy_decode(data,n,out);
  fclose(f); return status;
}
size_t ue_policy_result(const ue_policy_t *p,bool accepted,uint8_t out[13])
{
  out[0]=p->pti; out[1]=accepted?2:3;
  if (accepted) return 2;
  out[2]=0;out[3]=9;out[4]=1;memcpy(out+5,p->plmn,3);
  out[8]=p->upsc>>8;out[9]=p->upsc;out[10]=0;out[11]=1;out[12]=0x6f;
  return 13;
}
