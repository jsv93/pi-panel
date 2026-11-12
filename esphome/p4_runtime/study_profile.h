#pragma once
#include "../study_assets.h"
#include "fleet_client.h"
#include "light_client.h"
#include "climate_client.h"
#include "media_client.h"
#include "live_settings.h"

namespace study {
struct RoomProfile {
  int version=0;
  int soft[light_count]{},bright[light_count]{};
  bool members[light_count]{};
};
static p4_runtime::FleetClient<RoomProfile> fleet;
static p4_runtime::LightClient<light_count> ha_lights;
static p4_runtime::ClimateClient thermostat;
static p4_runtime::MediaClient player;
static RoomProfile factory_profile(){
  RoomProfile p;
  for(int i=0;i<light_count;i++){
    p.soft[i]=seed_soft[i];p.bright[i]=seed_bright[i];p.members[i]=seed_members[i];
  }
  return p;
}
static bool decode_room(const cJSON *doc,RoomProfile &out){
  using p4_runtime::Json;
  Json shape(cJSON_Duplicate(doc,true),cJSON_Delete);
  Json expected(cJSON_Parse(layout_contract),cJSON_Delete);
  if(!shape || !expected)return false;
  const auto *version=cJSON_GetObjectItemCaseSensitive(doc,"_version");
  if(!cJSON_IsNumber(version)||version->valuedouble<1||version->valuedouble!=version->valueint)return false;
  out.version=version->valueint;
  for(const char *key:{"_claimed","_panel_id","_version"})cJSON_DeleteItemFromObjectCaseSensitive(shape.get(),key);
  auto *lights=cJSON_GetObjectItemCaseSensitive(shape.get(),"lights");
  if(!cJSON_IsArray(lights)||cJSON_GetArraySize(lights)!=light_count)return false;
  for(int i=0;i<light_count;i++){
    auto *l=cJSON_GetArrayItem(lights,i);
    auto read_level=[&](const char *key,int fallback,int &dest){
      auto *v=cJSON_GetObjectItemCaseSensitive(l,key);
      if(!v){dest=fallback;return true;}
      if(!cJSON_IsNumber(v)||v->valuedouble!=v->valueint||v->valueint<0||v->valueint>100)return false;
      dest=v->valueint;return true;
    };
    if(!read_level("soft",30,out.soft[i])||!read_level("bright",100,out.bright[i]))return false;
    auto *member=cJSON_GetObjectItemCaseSensitive(l,"include_presets");
    if(member&&!cJSON_IsBool(member))return false;
    out.members[i]=!member||cJSON_IsTrue(member);
    for(const char *key:{"soft","bright","include_presets"})cJSON_DeleteItemFromObjectCaseSensitive(l,key);
  }
  // A baked label must never operate a newly assigned entity. A configuration
  // requiring different artwork stays pending and the usable cache survives.
  return cJSON_Compare(shape.get(),expected.get(),true);
}
static bool live_dirty[light_count]{};
static int last_on[light_count]{};
static void room_start(){
  fleet.begin(fleet_settings,decode_room,factory_profile());
  thermostat.start(temperature_entity,humidity_entity,climate_entity);
  player.start(initial_speaker);
  ha_lights.start(room_entities,[](size_t i,int value){
    live_dirty[i]=true;
    ESP_LOGI("study","HA light %u confirmed %d",unsigned(i),value);
    if(value>0)last_on[i]=value;
  });
}
}
