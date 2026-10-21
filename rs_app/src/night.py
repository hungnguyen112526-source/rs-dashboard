"""Nền 'Temple Night' (ThreeUI): lựa chọn thêm bên cạnh sáng/tối của Streamlit."""
import streamlit as st

SRC = "app/static/temple_night.html"   # cần [server] enableStaticServing = true

CSS = """<style>
.stApp,[data-testid="stAppViewContainer"],[data-testid="stHeader"],[data-testid="stSidebar"]{background:transparent!important}
[data-testid="stAppViewContainer"],[data-testid="stSidebar"]{position:relative;z-index:1}
[data-testid="stVerticalBlockBorderWrapper"],[data-testid="stExpander"],[data-testid="stDialog"] > div{
 background:rgba(8,12,16,.68)!important;backdrop-filter:blur(14px);border-radius:16px}
.stApp,.stApp p,.stApp label,.stApp h1,.stApp h2,.stApp h3{color:#e9eef0}
</style>"""

JS = """<script>
(function(){var d=document,id='tn-bg',on=%s,el=d.getElementById(id);
if(!on){if(el){el.remove();}return;}
if(el)return;
var f=d.createElement('iframe');f.id=id;f.src='%s';
f.style.cssText='position:fixed;inset:0;width:100vw;height:100vh;border:0;z-index:0;pointer-events:none';
d.body.prepend(f);d.body.style.background='#05070a';
addEventListener('pointermove',function(e){f.contentWindow&&f.contentWindow.postMessage({tn:1,inside:true,
x:e.clientX/innerWidth*2-1,y:1-e.clientY/innerHeight*2},'*')},{passive:true});
d.addEventListener('pointerleave',function(){f.contentWindow&&f.contentWindow.postMessage({tn:1,inside:false,x:0,y:0},'*')});
})();</script>"""

def render(on: bool) -> None:
    """Gọi ở đầu app và mỗi lần chạy lại: bật thì chèn nền + CSS, tắt thì gỡ nền."""
    if on:
        st.html(CSS)
    st.html(JS % ("true" if on else "false", SRC), unsafe_allow_javascript=True)

def toggle() -> bool:
    """Ô chọn trong sidebar; trả về True nếu đang bật."""
    on = st.toggle("🌙 Nền Temple Night", key="temple_night")
    if on and getattr(st.context.theme, "type", None) == "light":
        st.caption("Nên bật theme **Tối** (⋮ → Settings → Theme) để bảng và ô chọn đọc rõ trên nền đêm.")
    return on
