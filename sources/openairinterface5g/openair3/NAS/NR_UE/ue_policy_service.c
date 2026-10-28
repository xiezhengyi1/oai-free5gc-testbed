/* SPDX-License-Identifier: LicenseRef-CSSL-1.0 */
#include "ue_policy_service.h"
#include <arpa/inet.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <time.h>

void ue_policy_write_state(nr_ue_nas_t *nas)
{
  if (!nas->policy_dynamic_pdu) return;
  char path[560], temporary[564];
  snprintf(path,sizeof(path),"%s.state.json",nas->policy_path);
  snprintf(temporary,sizeof(temporary),"%s.tmp",path);
  FILE *file=fopen(temporary,"w");
  AssertFatal(file,"Cannot write UE NAS state: %s\n",strerror(errno));
  fprintf(file,"{\"source\":\"oai_ue_nas\",\"allowed_nssai\":[");
  for (int i=0;i<nas->policy_allowed_count;i++)
    fprintf(file,"%s{\"sst\":%d,\"sd\":\"%06x\"}",i?",":"",nas->policy_allowed_nssai[i].sst,nas->policy_allowed_nssai[i].sd);
  fprintf(file,"],\"sessions\":[");
  for (int i=0;i<nas->uicc->n_pdu_sessions;i++) {
    const pdu_session_config_t *p=&nas->uicc->pdu_sessions[i];
    fprintf(file,"%s{\"id\":%d,\"dnn\":\"%s\",\"sst\":%d,\"sd\":\"%06x\",\"active\":%s,\"pending\":%s,\"error\":%d}",
            i?",":"",p->id,p->dnn,p->nssai.sst,p->nssai.sd,
            nas->policy_session_active[p->id]?"true":"false",nas->policy_session_pending[p->id]?"true":"false",nas->policy_session_error[p->id]);
  }
  fprintf(file,"]}\n");
  AssertFatal(fclose(file)==0 && rename(temporary,path)==0,"Cannot commit UE NAS state\n");
}

static int select_session(nr_ue_nas_t *nas,const ue_policy_rule_t *rule)
{
  const ue_policy_route_t *route=NULL;
  for (size_t j=0;j<rule->route_count;j++) {
    const ue_policy_route_t *candidate=&rule->routes[j];
    bool allowed=false;
    if (!nas->policy_dynamic_pdu) {
      for (int i=0;i<nas->uicc->n_pdu_sessions;i++) {
        const pdu_session_config_t *p=&nas->uicc->pdu_sessions[i];
        if (!strcmp(p->dnn,candidate->dnn) && p->nssai.sst==candidate->sst && p->nssai.sd==candidate->sd
            && nas->policy_session_active[p->id]) allowed=true;
      }
    } else {
      for (int i=0;i<nas->policy_allowed_count;i++)
        if (nas->policy_allowed_nssai[i].sst==candidate->sst &&
            nas->policy_allowed_nssai[i].sd==candidate->sd) allowed=true;
    }
    if (allowed && (!route || candidate->precedence<route->precedence)) route=candidate;
  }
  if (!route) return -1;
  for (int i=0;i<nas->uicc->n_pdu_sessions;i++) {
    const pdu_session_config_t *p=&nas->uicc->pdu_sessions[i];
    if (!strcmp(p->dnn,route->dnn) && p->nssai.sst==route->sst && p->nssai.sd==route->sd) return i;
  }
  if (!nas->policy_dynamic_pdu) return -1;
  int id;
  for (id=1;id<16;id++) {
    bool used=false;
    for (int i=0;i<nas->uicc->n_pdu_sessions;i++) used|=nas->uicc->pdu_sessions[i].id==id;
    if (!used) break;
  }
  if (id==16) return -1;
  int index=nas->uicc->n_pdu_sessions++;
  nas->uicc->pdu_sessions[index]=(pdu_session_config_t){.id=id,.type=1,
    .nssai={.sst=route->sst,.sd=route->sd},.dnn=strdup(route->dnn)};
  AssertFatal(nas->uicc->pdu_sessions[index].dnn,"Cannot allocate PDU DNN\n");
  return index;
}

static void *serve(void *arg)
{
  nr_ue_nas_t *nas=arg;
  int listener=socket(AF_UNIX,SOCK_STREAM,0);
  AssertFatal(listener>=0,"UE policy socket: %s\n",strerror(errno));
  struct sockaddr_un address={.sun_family=AF_UNIX};
  int n=snprintf(address.sun_path,sizeof(address.sun_path),"%s.sock",nas->policy_path);
  AssertFatal(n<(int)sizeof(address.sun_path),"UE policy socket path too long\n");
  unlink(address.sun_path);
  AssertFatal(bind(listener,(struct sockaddr *)&address,sizeof(address))==0,"UE policy bind: %s\n",strerror(errno));
  AssertFatal(listen(listener,8)==0,"UE policy listen: %s\n",strerror(errno));
  for (;;) {
    int fd=accept(listener,NULL,NULL);
    if (fd<0) { LOG_E(NAS,"UE policy accept: %s\n",strerror(errno)); break; }
    struct timeval timeout={.tv_sec=2};
    setsockopt(fd,SOL_SOCKET,SO_RCVTIMEO,&timeout,sizeof(timeout));
    char query[128]={0},ip[INET_ADDRSTRLEN]; unsigned protocol,port;
    ssize_t got=recv(fd,query,sizeof(query)-1,0);
    struct in_addr ipv4;
    if (got<=0 || sscanf(query,"%15s %u %u",ip,&protocol,&port)!=3 || protocol>255 || port>65535 || inet_pton(AF_INET,ip,&ipv4)!=1) {
      send(fd,"ERROR invalid-query\n",20,MSG_NOSIGNAL); close(fd); continue;
    }
    pthread_mutex_lock(&nas->ue_policy_lock);
    const ue_policy_rule_t *rule=ue_policy_match(&nas->ue_policy,ntohl(ipv4.s_addr),protocol,port);
    int idx=rule?select_session(nas,rule):-1;
    char response[256];
    if (idx<0) {
      snprintf(response,sizeof(response),"NO_ROUTE\n");
    } else {
      const pdu_session_config_t *pdu=&nas->uicc->pdu_sessions[idx];
      int id=pdu->id;
      if (nas->policy_dynamic_pdu && !nas->policy_session_active[id] && !nas->policy_session_pending[id] && !nas->policy_session_error[id]) {
        nas->policy_session_pending[id]=true;
        nas->policy_session_started[id]=time(NULL);
        request_pdusession(nas,pdu);
        LOG_I(NAS,"UE_POLICY PDU_REQUEST id=%d dnn=%s sst=%d sd=%06x\n",id,pdu->dnn,pdu->nssai.sst,pdu->nssai.sd);
        ue_policy_write_state(nas);
      }
      if (nas->policy_session_pending[id] && time(NULL)-nas->policy_session_started[id]>30) {
        nas->policy_session_pending[id]=false;
        nas->policy_session_error[id]=-1;
        ue_policy_write_state(nas);
      }
      if (nas->policy_session_error[id]) {
        snprintf(response,sizeof(response),"FAILED %d %d\n",id,nas->policy_session_error[id]);
      } else if (!nas->policy_session_active[pdu->id]) {
        snprintf(response,sizeof(response),"PENDING %d\n",pdu->id);
      } else {
        char interface[32];
        if (idx==0) snprintf(interface,sizeof(interface),"oaitun_ue%ld",nas->UE_id+1);
        else snprintf(interface,sizeof(interface),"oaitun_ue%ldp%d",nas->UE_id+1,pdu->id);
        snprintf(response,sizeof(response),"ROUTE %s %d %u %u %u\n",interface,pdu->id,rule->precedence,nas->ue_policy.upsc,nas->ue_policy.pti);
      }
    }
    pthread_mutex_unlock(&nas->ue_policy_lock);
    send(fd,response,strlen(response),MSG_NOSIGNAL);
    close(fd);
  }
  close(listener); return NULL;
}
void ue_policy_service_start(nr_ue_nas_t *nas)
{
  pthread_mutex_init(&nas->ue_policy_lock,NULL);
  const char *dir=getenv("OAI_UE_POLICY_DIR");
  if (!dir) return;
  int n=snprintf(nas->policy_path,sizeof(nas->policy_path),"%s/%s.policy",dir,nas->uicc->imsiStr);
  AssertFatal(n<(int)sizeof(nas->policy_path),"UE policy storage path too long\n");
  AssertFatal(ue_policy_load(nas->policy_path,&nas->ue_policy)>=0,"Cannot load UE policy file\n");
  nas->policy_dynamic_pdu=getenv("OAI_UE_DYNAMIC_PDU") && !strcmp(getenv("OAI_UE_DYNAMIC_PDU"),"1");
  for (int i=0;i<nas->uicc->n_pdu_sessions;i++)
    AssertFatal(nas->uicc->pdu_sessions[i].id>0 && nas->uicc->pdu_sessions[i].id<16,"PDU session identity must be 1..15\n");
  ue_policy_write_state(nas);
  pthread_t thread;
  AssertFatal(pthread_create(&thread,NULL,serve,nas)==0,"Cannot start UE policy service\n");
  pthread_detach(thread);
}
