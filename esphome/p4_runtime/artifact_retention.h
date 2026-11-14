#pragma once
#include <cerrno>
#include <atomic>
#include <vector>
#include "nvs.h"

namespace p4_runtime {
// Only hashes explicitly adopted from this device's firmware or a verified
// signed offer are owned. Never enumerate/delete arbitrary card contents.
// The journal is committed before downloading, and keeps both healthy banks.
class ArtifactRetention {
  struct Journal {
    uint32_t magic=0x50345231, count=0;
    uint8_t active[6][32]{}, previous[6][32]{}, owned[32][32]{};
  } journal_;
  bool save(){
    nvs_handle_t h;if(nvs_open("p4-update",NVS_READWRITE,&h)!=ESP_OK)return false;
    const bool ok=nvs_set_blob(h,"artifacts-v1",&journal_,sizeof(journal_))==ESP_OK && nvs_commit(h)==ESP_OK;
    nvs_close(h);return ok;
  }
  static bool matches(const uint8_t *a,const uint8_t *b){return !memcmp(a,b,32);}
  bool include(const uint8_t *hash){
    for(unsigned i=0;i<journal_.count;++i)if(matches(journal_.owned[i],hash))return true;
    if(journal_.count==32)return false;
    memcpy(journal_.owned[journal_.count++],hash,32);return true;
  }
  bool protected_hash(const uint8_t *hash,const std::vector<const uint8_t*> &incoming)const{
    for(unsigned i=0;i<6;++i)if(matches(hash,journal_.active[i]) || matches(hash,journal_.previous[i]))return true;
    for(const auto *keep:incoming)if(matches(hash,keep))return true;
    return false;
  }
 public:
  bool boot(const std::vector<const uint8_t*> &current){
    if(current.size()!=6)return false;
    nvs_handle_t h;
    if(nvs_open("p4-update",NVS_READONLY,&h)==ESP_OK){
      size_t bytes=sizeof(journal_);
      const auto result=nvs_get_blob(h,"artifacts-v1",&journal_,&bytes);nvs_close(h);
      if(result!=ESP_ERR_NVS_NOT_FOUND && (result!=ESP_OK || bytes!=sizeof(journal_) || journal_.magic!=0x50345231 || journal_.count>32))return false;
    }
    bool same=true;for(unsigned i=0;i<6;++i)same=same && matches(current[i],journal_.active[i]);
    if(!same){
      memcpy(journal_.previous,journal_.active,sizeof(journal_.active));
      for(unsigned i=0;i<6;++i){memcpy(journal_.active[i],current[i],32);if(!include(current[i]))return false;}
    }
    return save();
  }
  bool prepare(const std::vector<const uint8_t*> &incoming,const std::atomic<bool> &idle){
    for(unsigned i=0;i<journal_.count;){
      if(protected_hash(journal_.owned[i],incoming)){++i;continue;}
      if(!idle.load())return false;
      char hex[65]{};for(unsigned j=0;j<32;++j)snprintf(hex+2*j,3,"%02x",journal_.owned[i][j]);
      const std::string root=std::string("/sd/pi-panel/")+hex;
      // A failed unlink leaves the journal entry intact, so a power loss or
      // temporarily busy card cannot turn a leftover file into untracked data.
      bool ok=true;
      for(const auto *suffix:{".part",".bin"})if(remove((root+suffix).c_str()) && errno!=ENOENT)ok=false;
      if(!ok)return false;
      memcpy(journal_.owned[i],journal_.owned[--journal_.count],32);
      if(!save())return false;
      vTaskDelay(1);
    }
    for(const auto *hash:incoming)if(!include(hash))return false;
    return save();
  }
};
}
