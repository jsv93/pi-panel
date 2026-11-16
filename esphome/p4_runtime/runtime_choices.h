#pragma once
#include <cmath>
#include <cstring>
#include <type_traits>

namespace study {
struct RuntimeChoices {
  double idle=45,off=0,brightness=100,minimum=5;
  double adaptive_min=10,adaptive_max=100,dark=5,bright=300,transition=5;
  bool adaptive=false,bell=false;
  int duration=30,speaker=0,presence_pin=-1,presence_debounce=10000;
  int speakers=0;
  char speaker_ids[16][97]{},speaker_names[16][97]{};
  char lux[97]{},camera[97]{},trigger[97]{},temperature[97]{},humidity[97]{},climate[97]{};
};
static_assert(std::is_trivially_copyable<RuntimeChoices>::value,"Fleet queue requires value storage");
static bool read_runtime_choices(const cJSON *doc,RuntimeChoices &r){
  auto object=[&](const char *key){return cJSON_GetObjectItemCaseSensitive(doc,key);};
  auto *display=object("display"),*bell=object("doorbell"),*sensors=object("sensors"),*media=object("media");
  for(auto *section:{display,bell,sensors,media})if(section && !cJSON_IsObject(section))return false;
  auto number=[](const cJSON *parent,const char *key,double fallback,double lo,double hi,double &out){
    auto *v=cJSON_GetObjectItemCaseSensitive(parent,key);out=v?v->valuedouble:fallback;
    return (!v || cJSON_IsNumber(v)) && std::isfinite(out) && out>=lo && out<=hi;
  };
  auto integer=[&](const cJSON *parent,const char *key,int fallback,int lo,int hi,int &out){
    double n;if(!number(parent,key,fallback,lo,hi,n) || n!=int(n))return false;out=int(n);return true;
  };
  auto boolean=[](const cJSON *parent,const char *key,bool fallback,bool &out){
    auto *v=cJSON_GetObjectItemCaseSensitive(parent,key);out=v?cJSON_IsTrue(v):fallback;
    return !v || cJSON_IsBool(v);
  };
  auto entity=[](const cJSON *parent,const char *key,const char *domain,char *out){
    auto *v=cJSON_GetObjectItemCaseSensitive(parent,key);
    if(v && !cJSON_IsString(v))return false;
    const char *s=v?v->valuestring:"";const size_t n=strlen(s);
    if(n>96)return false;
    if(n){
      if(domain && strncmp(s,domain,strlen(domain)))return false;
      bool dot=false;
      for(size_t i=0;i<n;++i){char c=s[i];if(c=='.'){if(dot || !i || i+1==n)return false;dot=true;}
        else if(!((c>='a'&&c<='z') || (c>='0'&&c<='9') || c=='_'))return false;}
      if(!dot)return false;
    }
    memcpy(out,s,n+1);return true;
  };
  if(!number(display,"idle_timeout_s",45,0,86400,r.idle) ||
     !number(display,"backlight_off_s",0,0,86400,r.off) ||
     !number(display,"backlight_default",100,1,100,r.brightness) ||
     !number(display,"backlight_min",5,1,100,r.minimum) ||
     !number(display,"adaptive_min_pct",10,1,100,r.adaptive_min) ||
     !number(display,"adaptive_max_pct",100,1,100,r.adaptive_max) ||
     !number(display,"adaptive_dark_lux",5,0,100000,r.dark) ||
     !number(display,"adaptive_bright_lux",300,1,200000,r.bright) ||
     !number(display,"adaptive_transition_s",5,1,60,r.transition) ||
     !boolean(display,"adaptive_brightness",false,r.adaptive) ||
     !entity(display,"adaptive_sensor","sensor.",r.lux) ||
     r.adaptive_min>r.adaptive_max || r.dark>=r.bright || (r.adaptive && !*r.lux) ||
     !boolean(bell,"enabled",false,r.bell) || !integer(bell,"duration_s",30,10,120,r.duration) ||
     !entity(bell,"camera","camera.",r.camera) || !entity(bell,"trigger",nullptr,r.trigger) ||
     (r.bell && !*r.camera) || !entity(sensors,"temperature","sensor.",r.temperature) ||
     !entity(sensors,"humidity","sensor.",r.humidity) || !entity(sensors,"climate","climate.",r.climate) ||
     !integer(display,"p4_presence_pin",-1,-1,54,r.presence_pin) ||
     !integer(display,"p4_presence_debounce_ms",10000,500,60000,r.presence_debounce))return false;
  // Only dedicated, unoccupied header pins are offered for this board.
  if(r.presence_pin!=-1 && r.presence_pin!=2 && r.presence_pin!=3)return false;
  char speaker[97]{};if(!entity(media,"default_speaker","media_player.",speaker))return false;
  r.speaker=0;r.speakers=0;
  auto add=[&](const char *id,const char *name){
    if(r.speakers==16 || !*id || strlen(id)>96 || strlen(name)>96)return false;
    for(int i=0;i<r.speakers;++i)if(!strcmp(id,r.speaker_ids[i]))return false;
    snprintf(r.speaker_ids[r.speakers],97,"%s",id);
    snprintf(r.speaker_names[r.speakers++],97,"%s",*name?name:strchr(id,'.')+1);return true;
  };
  auto *list=cJSON_GetObjectItemCaseSensitive(media,"speakers");
  if(list && !cJSON_IsArray(list))return false;
  bool found=false;auto *entry=static_cast<cJSON*>(nullptr);
  cJSON_ArrayForEach(entry,list){
    char id[97]{};const char *name="";
    if(cJSON_IsString(entry)){
      // Reuse the same strict entity validator for the shorthand form.
      cJSON object{};cJSON copy=*entry;copy.string=const_cast<char*>("entity_id");copy.next=nullptr;object.child=&copy;
      if(!entity(&object,"entity_id","media_player.",id))return false;
    }else if(cJSON_IsObject(entry)){
      if(!entity(entry,"entity_id","media_player.",id))return false;
      auto *label=cJSON_GetObjectItemCaseSensitive(entry,"name");
      if(label && !cJSON_IsString(label))return false;
      if(label)name=label->valuestring;
    }else return false;
    if(!add(id,name))return false;
    if(!strcmp(speaker,id)){r.speaker=r.speakers-1;found=true;}
  }
  if(*speaker && !found){
    auto *name=cJSON_GetObjectItemCaseSensitive(media,"default_speaker_name");
    if(name && !cJSON_IsString(name))return false;
    if(!add(speaker,name?name->valuestring:""))return false;
    char id[97],label[97];memcpy(id,r.speaker_ids[r.speakers-1],97);memcpy(label,r.speaker_names[r.speakers-1],97);
    for(int i=r.speakers-1;i>0;--i){memcpy(r.speaker_ids[i],r.speaker_ids[i-1],97);memcpy(r.speaker_names[i],r.speaker_names[i-1],97);}
    memcpy(r.speaker_ids[0],id,97);memcpy(r.speaker_names[0],label,97);r.speaker=0;
  }
#ifndef STUDY_ARCHITECTURAL_ONLY
  // Legacy card themes still have baked speaker labels. Never let a newly
  // assigned entity operate through one of those unchanged labels.
  if(r.speakers!=speaker_count)return false;
  for(int i=0;i<speaker_count;++i)if(strcmp(r.speaker_ids[i],speaker_ids[i]) || strcmp(r.speaker_names[i],speaker_labels[i]))return false;
#endif
  return true;
}
static void strip_runtime_choices(cJSON *doc){
  auto *d=cJSON_GetObjectItemCaseSensitive(doc,"display");
  for(const char *key:{"idle_timeout_s","backlight_off_s","backlight_default","backlight_min",
      "adaptive_brightness","adaptive_sensor","adaptive_min_pct","adaptive_max_pct","adaptive_dark_lux",
      "adaptive_bright_lux","adaptive_transition_s","p4_presence_pin","p4_presence_debounce_ms",
      "browser_recovery","browser_stale_s","browser_recovery_limit","remote_diagnostics","idle_power_saving",
      "presence_pin","presence_sensor","presence_debounce_ms"})cJSON_DeleteItemFromObjectCaseSensitive(d,key);
  auto *bell=cJSON_GetObjectItemCaseSensitive(doc,"doorbell");
  if(!bell)bell=cJSON_AddObjectToObject(doc,"doorbell");
  for(const char *key:{"enabled","duration_s","camera","trigger"})cJSON_DeleteItemFromObjectCaseSensitive(bell,key);
  auto *title=cJSON_GetObjectItemCaseSensitive(bell,"title");
  if(!title || (cJSON_IsString(title) && !*title->valuestring)){
    cJSON_DeleteItemFromObjectCaseSensitive(bell,"title");cJSON_AddStringToObject(bell,"title","Someone at the door");
  }
  auto *sensors=cJSON_GetObjectItemCaseSensitive(doc,"sensors");
  if(!sensors)sensors=cJSON_AddObjectToObject(doc,"sensors");
  for(const char *key:{"temperature","humidity","climate"})cJSON_DeleteItemFromObjectCaseSensitive(sensors,key);
  for(const char *key:{"default_speaker","default_speaker_name","speakers"})
    cJSON_DeleteItemFromObjectCaseSensitive(cJSON_GetObjectItemCaseSensitive(doc,"media"),key);
}
}
