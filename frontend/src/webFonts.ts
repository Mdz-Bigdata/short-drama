// 品牌字体(Outfit + Noto Sans SC)来自谷歌字体。写成样式表里的 @import 时，首屏要等这个外站
// 回话，连不上就一直白着；改成页面脚本起来后再挂 <link>，脚本插入的样式表不挡渲染。
// 取不到时界面用 index.css 字体栈里的系统黑体，字到了再换上(display=swap)。
const WEB_FONTS_STYLESHEET = 'https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700;800&family=Noto+Sans+SC:wght@300;400;500;700&display=swap';
const WEB_FONTS_FILE_ORIGIN = 'https://fonts.gstatic.com';
const MARKER = 'data-web-fonts';

export function loadWebFonts(doc: Document = document): void {
  if (doc.head.querySelector(`link[${MARKER}]`)) return;

  const preconnect = doc.createElement('link');
  preconnect.rel = 'preconnect';
  preconnect.href = WEB_FONTS_FILE_ORIGIN;
  preconnect.crossOrigin = 'anonymous';
  preconnect.setAttribute(MARKER, '');

  const stylesheet = doc.createElement('link');
  stylesheet.rel = 'stylesheet';
  stylesheet.href = WEB_FONTS_STYLESHEET;
  stylesheet.setAttribute(MARKER, '');

  doc.head.append(preconnect, stylesheet);
}
