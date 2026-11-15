"""Measure the CM5 mini-player without rebuilding its artwork."""
from render import fixture_page
from control_art import box
from palette_art import PALETTES


def generate(config, output, chromium_cdp=None):
    def array(items):
        return '{'+','.join(array(x) if isinstance(x, (list, tuple)) else str(x) for x in items)+'}'
    with fixture_page(config, [], chromium_cdp=chromium_cdp) as page:
        page.evaluate("""() => {
          const strip=document.querySelector('#roomMedia');
          strip.hidden=false;strip.classList.add('playing');strip.classList.remove('idle');
          document.querySelector('#rmTitle').textContent='Playing';
        }""")
        page.add_style_tag(content='#rmEq i{animation:none!important;transform:none!important}')
        bars=[]
        for cover in (False, True):
            page.evaluate("""cover=>{
              document.body.classList.toggle('no-mini-art',!cover);
              const art=document.querySelector('#roomMedia .art');
              art.replaceChildren();if(cover)art.appendChild(document.createElement('img'));
            }""", cover)
            bars.append([box(page, f'#rmEq i:nth-child({i+1})') for i in range(4)])
        colours=[]
        for palette in PALETTES:
            page.evaluate("""name=>{
              document.body.classList.remove(...Array.from(document.body.classList).filter(x=>x.startsWith('pal-')));
              document.body.classList.add('pal-'+name);
            }""", palette)
            r,g,b=page.locator('#rmEq i').first.evaluate('e=>getComputedStyle(e).backgroundColor.match(/\\d+/g).map(Number)')[:3]
            colours.append((r>>3)<<11 | (g>>2)<<5 | (b>>3))
    output.write_text('#pragma once\nnamespace study {\nconstexpr Rect mini_bars[2][4]='+array(bars)+
                      ';\nconstexpr uint16_t mini_colours[6]='+array(colours)+';\n}\n', encoding='ascii')
