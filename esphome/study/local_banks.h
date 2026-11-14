#pragma once
#include "local_bank_assets.h"
#include "card_art.h"

namespace study {
// Immutable files let each OTA application keep its own matching artwork.
// The shared flash data partition is never modified by a network update.
static uint8_t *load_local_bank(const LocalBank &bank){
  CardArt file;
  if(!file.mount() || !file.open(bank.path,bank.bytes,bank.sha))return nullptr;
  auto *bytes=static_cast<uint8_t*>(heap_caps_malloc(bank.bytes,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT));
  if(bytes && !file.read(0,bytes,bank.bytes)){heap_caps_free(bytes);bytes=nullptr;}
  return bytes;
}
}
