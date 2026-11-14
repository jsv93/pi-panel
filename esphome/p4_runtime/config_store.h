#pragma once
#include <cJSON.h>
#include <mbedtls/md.h>
#include <nvs.h>
#include <algorithm>
#include <cctype>
#include <cmath>
#include <cstring>
#include <memory>
#include <string>
#include <vector>

namespace p4_runtime {
constexpr size_t config_limit=48*1024;
using Json=std::unique_ptr<cJSON,decltype(&cJSON_Delete)>;

inline const char *field(const cJSON *obj,const char *name){
  auto *item=cJSON_GetObjectItemCaseSensitive(obj,name);
  return cJSON_IsString(item)?item->valuestring:"";
}

// Old servers sign sorted compact JSON but send the fields in display order.
// Support their ASCII / integral Study profiles. Other representations go
// through the exact-byte protocol. Every path still verifies the same HMAC.
inline bool legacy_value(const cJSON *node,std::string &out,unsigned depth=0){
  if(!node || depth>32 || out.size()>config_limit)return false;
  if(cJSON_IsObject(node) || cJSON_IsArray(node)){
    const bool object=cJSON_IsObject(node);
    std::vector<const cJSON*> children;
    for(auto *child=node->child;child;child=child->next)children.push_back(child);
    if(object)std::sort(children.begin(),children.end(),[](auto *a,auto *b){return strcmp(a->string,b->string)<0;});
    out+=object?'{':'[';
    bool first=true;
    for(auto *child:children){
      if(!first)out+=',';
      first=false;
      if(object){
        Json name(cJSON_CreateString(child->string),cJSON_Delete);
        if(!legacy_value(name.get(),out,depth+1))return false;
        out+=':';
      }
      if(!legacy_value(child,out,depth+1))return false;
    }
    out+=object?'}':']';
  }else if(cJSON_IsNumber(node)){
    if(!std::isfinite(node->valuedouble) || std::abs(node->valuedouble)>9007199254740991.0 ||
       std::trunc(node->valuedouble)!=node->valuedouble)return false;
    out+=std::to_string(static_cast<long long>(node->valuedouble));
  }else{
    if(cJSON_IsString(node))for(const unsigned char *p=reinterpret_cast<const unsigned char*>(node->valuestring);*p;p++)
      if(*p>126)return false;
    char *encoded=cJSON_PrintUnformatted(node);
    if(!encoded)return false;
    out+=encoded;cJSON_free(encoded);
  }
  return out.size()<=config_limit;
}
inline bool unpack_legacy(std::string &body,std::string &signature){
  Json doc(cJSON_ParseWithLengthOpts(body.c_str(),body.size()+1,nullptr,true),cJSON_Delete);
  if(!doc)return false;
  signature=field(doc.get(),"_sig");
  if(signature.size()!=64)return false;
  cJSON_DeleteItemFromObjectCaseSensitive(doc.get(),"_sig");
  std::string canonical;
  if(!legacy_value(doc.get(),canonical))return false;
  body.swap(canonical);
  return true;
}
inline Json verified_config(const std::string &body,const std::string &signature,const char *key,const char *id){
  Json result(nullptr,cJSON_Delete);
  if(body.empty() || body.size()>config_limit || signature.size()!=64)return result;
  unsigned char digest[32];
  if(mbedtls_md_hmac(mbedtls_md_info_from_type(MBEDTLS_MD_SHA256),
           reinterpret_cast<const unsigned char*>(key),strlen(key),
           reinterpret_cast<const unsigned char*>(body.data()),body.size(),digest)!=0)return result;
  static constexpr char hex[]="0123456789abcdef";
  unsigned diff=0;
  for(size_t n=0;n<32;n++){
    diff|=signature[n*2]^hex[digest[n]>>4];
    diff|=signature[n*2+1]^hex[digest[n]&15];
  }
  if(diff)return result;
  result.reset(cJSON_ParseWithLengthOpts(body.c_str(),body.size()+1,nullptr,true));
  if(!result || strcmp(field(result.get(),"_panel_id"),id) ||
     !cJSON_IsTrue(cJSON_GetObjectItemCaseSensitive(result.get(),"_claimed")) ||
     !cJSON_IsNumber(cJSON_GetObjectItemCaseSensitive(result.get(),"_version")))result.reset();
  return result;
}

// Signature and body are one NVS value. NVS atomically replaces a single
// value and recovers the previous committed value across an interrupted write.
inline bool save_config(const std::string &body,const std::string &sig){
  nvs_handle_t handle;
  if(nvs_open("panel-config",NVS_READWRITE,&handle)!=ESP_OK)return false;
  const auto record=sig+body;
  bool ok=nvs_set_blob(handle,"signed",record.data(),record.size())==ESP_OK && nvs_commit(handle)==ESP_OK;
  nvs_close(handle);
  return ok;
}
inline Json load_config(const char *key,const char *id,std::string &sig){
  Json result(nullptr,cJSON_Delete);
  nvs_handle_t handle;
  if(nvs_open("panel-config",NVS_READONLY,&handle)!=ESP_OK)return result;
  size_t size=0;
  if(nvs_get_blob(handle,"signed",nullptr,&size)==ESP_OK && size>64 && size<=64+config_limit){
    std::string record(size,'\0');
    if(nvs_get_blob(handle,"signed",record.data(),&size)==ESP_OK){
      result=verified_config(record.substr(64),record.substr(0,64),key,id);
      if(result)sig=record.substr(0,64);
    }
  }
  nvs_close(handle);
  return result;
}
}
