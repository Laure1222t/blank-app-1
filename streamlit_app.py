import streamlit as st
from PyPDF2 import PdfReader
from difflib import HtmlDiff
import base64
import time

# 设置页面标题和图标
st.set_page_config(
    page_title="在线PDF对比工具",
    page_icon="📄",
    layout="wide"
)

# 自定义CSS样式
st.markdown("""
<style>
    .stApp { max-width: 1200px; margin: 0 auto; }
    .stFileUploader { width: 100%; }
    .highlight-add { background-color: #d4edda; }
    .highlight-remove { background-color: #f8d7da; }
    .diff-container { border: 1px solid #ddd; border-radius: 5px; padding: 15px; }
</style>
""", unsafe_allow_html=True)

def extract_text_from_pdf(file):
    """从PDF提取文本"""
    try:
        pdf_reader = PdfReader(file)
        text = ""
        for page in pdf_reader.pages:
            text += page.extract_text() or ""  # 处理可能为None的情况
        return text
    except Exception as e:
        st.error(f"提取文本失败: {str(e)}")
        return ""

def create_download_link(content, filename, text):
    """生成下载链接"""
    b64 = base64.b64encode(content.encode()).decode()
    return f'<a href="data:file/txt;base64,{b64}" download="{filename}">{text}</a>'

def show_diff(text1, text2):
    """显示差异对比结果"""
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("文档1内容")
        st.text_area("内容1", text1, height=300, label_visibility="collapsed")
    
    with col2:
        st.subheader("文档2内容")
        st.text_area("内容2", text2, height=300, label_visibility="collapsed")
    
    st.divider()
    st.subheader("🔍 差异对比结果")
    
    # 使用HtmlDiff生成更美观的差异对比
    html_diff = HtmlDiff().make_file(
        text1.splitlines(), 
        text2.splitlines(),
        fromdesc="文档1",
        todesc="文档2"
    )
    
    # 在独立窗口中显示完整差异
    with st.expander("查看完整差异对比", expanded=True):
        st.components.v1.html(html_diff, height=600, scrolling=True)
    
    # 提供下载
    st.markdown(create_download_link(html_diff, "diff_result.html", "⬇️ 下载对比结果(HTML)"), unsafe_allow_html=True)

# 应用主界面
st.title("📄 在线PDF文档对比工具")
st.markdown("上传两个PDF文件，系统将自动解析并对比内容差异")

with st.form("upload_form"):
    col1, col2 = st.columns(2)
    with col1:
        file1 = st.file_uploader("选择第一个PDF文件", type=["pdf"])
    with col2:
        file2 = st.file_uploader("选择第二个PDF文件", type=["pdf"])
    
    submitted = st.form_submit_button("开始对比")

if submitted and file1 and file2:
    with st.spinner("正在解析PDF内容，请稍候..."):
        text1 = extract_text_from_pdf(file1)
        text2 = extract_text_from_pdf(file2)
        
        if not text1 or not text2:
            st.error("无法提取文本内容，请确认PDF包含可提取的文本")
        else:
            show_diff(text1, text2)
            
            # 显示简单的统计信息
            st.divider()
            col1, col2, col3 = st.columns(3)
            col1.metric("文档1字数", len(text1))
            col2.metric("文档2字数", len(text2))
            col3.metric("相似度", f"{sum(1 for a,b in zip(text1, text2) if a==b)/max(len(text1), len(text2))*100:.1f}%")
else:
    st.info("请上传两个PDF文件后点击"开始对比"按钮")

# 添加使用说明
with st.expander("使用说明"):
    st.markdown("""
    1. 上传两个需要对比的PDF文件
    2. 点击"开始对比"按钮
    3. 查看文本差异对比结果
    4. 可以下载HTML格式的对比报告
    
    **注意:**
    - 仅支持文本型PDF，扫描件需要OCR处理
    - 大文件可能需要更长的处理时间
    - 隐私提示: 上传的文件仅用于临时处理，不会存储在服务器
    """)

# 添加页脚
st.divider()
st.markdown("""
<style>
.footer {
    font-size: 0.8rem;
    color: #666;
    text-align: center;
    margin-top: 2rem;
}
</style>
<div class="footer">
    PDF对比工具 | 使用Streamlit构建 | 数据不会保留在服务器
</div>
""", unsafe_allow_html=True)
