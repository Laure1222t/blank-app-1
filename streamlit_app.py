import streamlit as st
from PyPDF2 import PdfReader
from difflib import HtmlDiff
import base64
import time
from io import BytesIO
import zipfile

# 设置页面
st.set_page_config(
    page_title="多文件PDF对比工具",
    page_icon="📑",
    layout="wide"
)

# 自定义CSS
st.markdown("""
<style>
    .stApp { max-width: 1400px; }
    .stProgress > div > div > div > div { background: linear-gradient(to right, #4facfe, #00f2fe); }
    .stFileUploader > div > div > div > button { color: white; background: #4facfe; }
    .footer { font-size: 0.8rem; color: #666; text-align: center; margin-top: 2rem; }
    .diff-section { border: 1px solid #eee; border-radius: 5px; padding: 15px; margin-bottom: 20px; }
</style>
""", unsafe_allow_html=True)

def extract_text_from_pdf(file):
    """从PDF提取文本"""
    try:
        pdf_reader = PdfReader(BytesIO(file.getvalue()))
        text = ""
        for page in pdf_reader.pages:
            text += page.extract_text() or ""
        return text.strip()
    except Exception as e:
        st.error(f"提取文本失败: {str(e)}")
        return ""

def create_diff_html(text1, text2, filename1, filename2):
    """生成差异HTML"""
    html_diff = HtmlDiff().make_file(
        text1.splitlines(), 
        text2.splitlines(),
        fromdesc=f"基准文件: {filename1}",
        todesc=f"对比文件: {filename2}"
    )
    return html_diff

def create_download_zip(diff_results):
    """创建包含所有对比结果的ZIP文件"""
    zip_buffer = BytesIO()
    with zipfile.ZipFile(zip_buffer, "w") as zip_file:
        for i, (filename, diff_html) in enumerate(diff_results.items(), 1):
            zip_file.writestr(f"对比结果_{i}_{filename}.html", diff_html)
    zip_buffer.seek(0)
    return zip_buffer

# 应用主界面
st.title("📑 多文件PDF对比工具")
st.markdown("上传一个基准PDF文件和多个对比PDF文件，系统将自动分析差异")

with st.form("upload_form"):
    # 上传基准文件
    base_file = st.file_uploader("选择基准PDF文件", type=["pdf"], key="base_file")
    
    # 上传多个对比文件
    compare_files = st.file_uploader(
        "选择多个对比PDF文件", 
        type=["pdf"], 
        accept_multiple_files=True,
        key="compare_files"
    )
    
    submitted = st.form_submit_button("开始对比")

if submitted:
    if not base_file:
        st.warning("请上传基准PDF文件")
    elif not compare_files:
        st.warning("请上传至少一个对比PDF文件")
    else:
        with st.spinner("正在处理文件..."):
            # 提取基准文件文本
            base_text = extract_text_from_pdf(base_file)
            
            if not base_text:
                st.error("无法从基准文件中提取文本")
            else:
                diff_results = {}
                progress_bar = st.progress(0)
                total_files = len(compare_files)
                
                for i, compare_file in enumerate(compare_files, 1):
                    # 更新进度
                    progress = i / total_files
                    progress_bar.progress(progress)
                    
                    # 提取对比文件文本
                    compare_text = extract_text_from_pdf(compare_file)
                    
                    if not compare_text:
                        st.warning(f"无法从 {compare_file.name} 中提取文本，跳过此文件")
                        continue
                    
                    # 生成差异报告
                    with st.expander(f"对比结果: {compare_file.name}", expanded=i==1):
                        st.markdown(f"### 对比文件: {compare_file.name}")
                        
                        # 显示文本统计
                        col1, col2, col3 = st.columns(3)
                        col1.metric("基准文件字数", len(base_text))
                        col2.metric("对比文件字数", len(compare_text))
                        similarity = sum(1 for a,b in zip(base_text, compare_text) if a==b)/max(len(base_text), len(compare_text))*100
                        col3.metric("相似度", f"{similarity:.1f}%")
                        
                        # 生成并显示差异
                        diff_html = create_diff_html(base_text, compare_text, base_file.name, compare_file.name)
                        st.components.v1.html(diff_html, height=600, scrolling=True)
                        
                        # 保存结果
                        diff_results[compare_file.name] = diff_html
                    
                    time.sleep(0.1)  # 稍微延迟，让UI更新
                
                progress_bar.empty()
                
                # 提供所有结果的下载
                if diff_results:
                    st.markdown("---")
                    st.subheader("下载所有对比结果")
                    zip_buffer = create_download_zip(diff_results)
                    st.download_button(
                        label="⬇️ 下载全部对比结果(ZIP)",
                        data=zip_buffer,
                        file_name="pdf_comparison_results.zip",
                        mime="application/zip"
                    )

# 使用说明
with st.expander("使用说明"):
    st.markdown("""
    1. 上传一个基准PDF文件
    2. 上传多个需要对比的PDF文件
    3. 点击"开始对比"按钮
    4. 查看每个文件的对比结果
    5. 可以下载所有对比结果的ZIP压缩包
    
    **注意:**
    - 仅支持文本型PDF，扫描件需要OCR处理
    - 大文件可能需要更长的处理时间
    - 隐私提示: 上传的文件仅用于临时处理，不会存储在服务器
    """)

# 页脚
st.divider()
st.markdown('<div class="footer">PDF多文件对比工具 | 使用Streamlit构建 | 数据不会保留在服务器</div>', unsafe_allow_html=True)
