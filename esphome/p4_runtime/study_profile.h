#pragma once
#include "../study_assets.h"
#include "fleet_client.h"
#include "light_client.h"
#include "climate_client.h"
#include "media_client.h"
#include "doorbell_client.h"
#include "album_client.h"
#include "library_client.h"
#include "live_settings.h"
#include "runtime_choices.h"

#if defined(STUDY_CARD_PLAYER) || defined(STUDY_ARCHITECTURAL_ONLY)
#define STUDY_SCREEN_OPTIONS
#endif
namespace study {
struct GestureChoices {int points=0,hold_ms=600;bool remember=true;};
static bool read_gesture_choices(cJSON *display,GestureChoices &out){
  if(!cJSON_IsObject(display))return false;
  auto *mode=cJSON_GetObjectItemCaseSensitive(display,"touch_gesture");
  auto *points=cJSON_GetObjectItemCaseSensitive(display,"touch_points");
  auto *hold=cJSON_GetObjectItemCaseSensitive(display,"touch_hold_ms");
  auto *remember=cJSON_GetObjectItemCaseSensitive(display,"remember_last_state");
  auto integer=[](const cJSON *v,int lo,int hi){return !v ||
    (cJSON_IsNumber(v) && v->valuedouble==v->valueint && v->valueint>=lo && v->valueint<=hi);};
  if((mode && (!cJSON_IsString(mode) || (strcmp(mode->valuestring,"off") && strcmp(mode->valuestring,"lights")))) ||
     !integer(points,2,5) || !integer(hold,600,1500) || (remember && !cJSON_IsBool(remember)))return false;
  out.points=mode && !strcmp(mode->valuestring,"lights")?(points?points->valueint:3):0;
  out.hold_ms=hold?hold->valueint:600;out.remember=!remember || cJSON_IsTrue(remember);
  return true;
}
#ifdef STUDY_SCREEN_OPTIONS
constexpr const char *theme_keys[]={"default","ambient","architectural"};
constexpr const char *palette_keys[]={"linen","midnight","ember","slate","heath","mono"};
struct ScreenChoices {uint8_t theme=2,palette=0;bool diagnostics=false,tiles=false,mini_art=true;};
static bool read_screen_choices(cJSON *display,ScreenChoices &screen){
  if(!cJSON_IsObject(display))return false;
  auto index=[&](const char *key,const auto &names,int fallback)->int{
    auto *v=cJSON_GetObjectItemCaseSensitive(display,key);
    if(!v)return fallback;
    if(!cJSON_IsString(v))return -1;
    if(!*v->valuestring)return fallback;
    for(size_t i=0;i<std::size(names);++i)if(!strcmp(names[i],v->valuestring))return int(i);
    return -1;
  };
  int theme=index("theme",theme_keys,0);
  int palette=index("palette",palette_keys,theme==2?0:theme==1?2:1);
  if(theme<0 || palette<0)return false;
#ifdef STUDY_ARCHITECTURAL_ONLY
  theme=2;
#endif
  screen.theme=theme;screen.palette=palette;
  auto *diag=cJSON_GetObjectItemCaseSensitive(display,"diagnostics");
  auto *mini=cJSON_GetObjectItemCaseSensitive(display,"mini_art");
  auto *browse=cJSON_GetObjectItemCaseSensitive(display,"browse_view");
  if((mini && !cJSON_IsBool(mini)) || (diag && !cJSON_IsBool(diag)) || (browse && (!cJSON_IsString(browse) ||
     (strcmp(browse->valuestring,"list") && strcmp(browse->valuestring,"tiles")))))return false;
  screen.diagnostics=cJSON_IsTrue(diag);
  screen.mini_art=!mini || cJSON_IsTrue(mini);
  screen.tiles=browse && !strcmp(browse->valuestring,"tiles");
  return true;
}
#endif
struct RoomProfile {
  int version=0;
  GestureChoices gesture;
  RuntimeChoices runtime;
  int soft[light_count]{},bright[light_count]{};
  bool members[light_count]{};
#ifdef STUDY_SCREEN_OPTIONS
  ScreenChoices screen;
#endif
};
static p4_runtime::FleetClient<RoomProfile> fleet;
static p4_runtime::LightClient<light_count> ha_lights;
static p4_runtime::ClimateClient thermostat;
static p4_runtime::MediaClient players[speaker_capacity];
static int selected_speaker=0;
static p4_runtime::MediaClient &player(){return players[selected_speaker];}
static p4_runtime::DoorbellClient bell_client;
static p4_runtime::AlbumClient album_client,thumbnail_client;
static p4_runtime::LibraryClient library;
static RoomProfile factory_profile(){
  RoomProfile p;
  p4_runtime::Json factory(cJSON_Parse(layout_contract),cJSON_Delete);
  if(factory)read_gesture_choices(cJSON_GetObjectItemCaseSensitive(factory.get(),"display"),p.gesture);
  if(factory)read_runtime_choices(factory.get(),p.runtime);
#ifdef STUDY_SCREEN_OPTIONS
  if(factory)read_screen_choices(cJSON_GetObjectItemCaseSensitive(factory.get(),"display"),p.screen);
#endif
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
  if(!read_runtime_choices(doc,out.runtime))return false;
  strip_runtime_choices(shape.get());strip_runtime_choices(expected.get());
  auto *actual_display=cJSON_GetObjectItemCaseSensitive(shape.get(),"display");
  auto *expected_display=cJSON_GetObjectItemCaseSensitive(expected.get(),"display");
  if(!read_gesture_choices(actual_display,out.gesture))return false;
  for(const char *key:{"touch_gesture","touch_points","touch_hold_ms","remember_last_state"}){
    cJSON_DeleteItemFromObjectCaseSensitive(actual_display,key);
    cJSON_DeleteItemFromObjectCaseSensitive(expected_display,key);
  }
#ifdef STUDY_SCREEN_OPTIONS
  if(!read_screen_choices(actual_display,out.screen))return false;
  for(const char *key:{"theme","palette","diagnostics","browse_view","mini_art"}){
    cJSON_DeleteItemFromObjectCaseSensitive(actual_display,key);
    cJSON_DeleteItemFromObjectCaseSensitive(expected_display,key);
  }
#endif
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
  const auto &runtime=fleet.active().runtime;
  speaker_count=runtime.speakers;
  memcpy(speaker_ids,runtime.speaker_ids,sizeof(speaker_ids));
  memcpy(speaker_labels,runtime.speaker_names,sizeof(speaker_labels));
  thermostat.start(runtime.temperature,runtime.humidity,runtime.climate);
  selected_speaker=runtime.speaker;
  for(int i=0;i<speaker_count;i++)players[i].start(speaker_ids[i]);
#ifndef STUDY_BENCH_TEST
  album_client.start(ha_origin);
  thumbnail_client.start(ha_origin,true,&fleet_settings);
#endif
  bell_client.begin(fleet_settings,runtime.bell?runtime.trigger:"",runtime.bell?runtime.camera:"",ha_origin);
  ha_lights.start(room_entities,[](size_t i,int value){
    live_dirty[i]=true;
    ESP_LOGI("study","HA light %u confirmed %d",unsigned(i),value);
    if(value>0)last_on[i]=value;
  });
}
}
