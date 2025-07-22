import streamlit as st
import PyPDF2
import difflib
import os
from io import BytesIO
import tempfile

# 设置页面配置
st.set_page_config(
    page_title="PDF解析与对比分析工具",
    page_icon="📄",
    layout="wide"
)

# 页面标题
st.title("📄 PDF解析与对比分析工具")

# 辅助函数：从PDF中提取文本
def extract_text_from_pdf(pdf_file):
    """从上传的PDF文件中提取文本内容"""
    try:
        pdf_reader = PyPDF2.PdfReader(pdf_file)
        text = ""
        for page in pdf_reader.pages:
            page_text = page.extract_text()
            if page_text:
                text += page_text
        return text
    except Exception as e:
        st.error(f"提取PDF文本时出错: {str(e)}")
        return None

# 辅助函数：比较两个文本并返回差异
def compare_texts(text1, text2, filename1, filename2):
    """比较两个文本并返回差异结果"""
    if not text1 or not text2:
        st.warning("无法比较，一个或多个文本为空")
        return
    
    # 使用difflib进行文本比较
    d = difflib.HtmlDiff()
    diff = d.make_file(
        text1.splitlines(), 
        text2.splitlines(),
        fromdesc=filename1,
        todesc=filename2
    )
    
    # 显示差异结果
    st.subheader("文本差异比较结果")
    st.markdown("""
    <style>
        .diff_add { background-color: #ccffcc; }
        .diff_del { background-color: #ffcccc; text-decoration: line-through; }
        .diff_chg { background-color: #ffffcc; }
    </style>
    """, unsafe_allow_html=True)
    st.components.v1.html(diff, height=600, scrolling=True)

# 辅助函数：多个文件间的比较
def compare_multiple_files(files_dict):
    """比较多个文件，生成相似度矩阵"""
    if len(files_dict) < 2:
        st.warning("请至少上传两个文件进行比较")
        return
    
    filenames = list(files_dict.keys())
    texts = list(files_dict.values())
    
    st.subheader("多文件相似度矩阵")
    
    # 创建相似度矩阵
    similarity_matrix = []
    for i in range(len(texts)):
        row = []
        for j in range(len(texts)):
            if i == j:
                row.append(1.0)  # 自身相似度为1
            else:
                # 使用SequenceMatcher计算相似度
                matcher = difflib.SequenceMatcher(None, texts[i], texts[j])
                ratio = matcher.ratio()
                row.append(round(ratio, 4))
        similarity_matrix.append(row)
    
    # 显示相似度矩阵
    import pandas as pd
    df = pd.DataFrame(similarity_matrix, index=filenames, columns=filenames)
    st.dataframe(df.style.background_gradient(cmap="Greens"))
    
    # 找出最相似的文件对
    max_sim = -1
    max_pair = None
    for i in range(len(filenames)):
        for j in range(i+1, len(filenames)):
            if similarity_matrix[i][j] > max_sim:
                max_sim = similarity_matrix[i][j]
                max_pair = (filenames[i], filenames[j], max_sim)
    
    if max_pair:
        st.info(f"最相似的文件对: {max_pair[0]} 和 {max_pair[1]}，相似度: {max_pair[2]:.2%}")
        
        # 提供详细比较选项
        if st.button("查看这两个文件的详细差异"):
            compare_texts(
                files_dict[max_pair[0]], 
                files_dict[max_pair[1]],
                max_pair[0],
                max_pair[1]
            )

# 主功能区
def main():
    # 侧边栏 - 功能选择
    st.sidebar.header("功能选择")
    function_choice = st.sidebar.radio(
        "请选择要执行的操作",
        ("PDF解析", "单文件对比", "多文件对比分析")
    )
    
    # 存储上传的文件及其内容
    if 'uploaded_files' not in st.session_state:
        st.session_state.uploaded_files = {}
    
    # PDF解析功能
    if function_choice == "PDF解析":
        st.header("PDF解析")
        st.write("上传PDF文件，提取并查看其文本内容")
        
        uploaded_file = st.file_uploader("选择PDF文件", type="pdf", key="pdf_parser")
        
        if uploaded_file is not None:
            # 保存到会话状态
            filename = uploaded_file.name
            if filename not in st.session_state.uploaded_files:
                text = extract_text_from_pdf(uploaded_file)
                if text:
                    st.session_state.uploaded_files[filename] = text
            
            # 显示文件信息
            st.success(f"已成功解析: {filename}")
            
            # 显示提取的文本
            if filename in st.session_state.uploaded_files:
                text = st.session_state.uploaded_files[filename]
                st.subheader("提取的文本内容")
                
                # 文本长度信息
                st.info(f"文本长度: {len(text)} 字符，约 {len(text.split())} 个单词")
                
                # 文本显示区域
                with st.expander("查看完整文本", expanded=True):
                    st.text_area("", text, height=500)
    
    # 单文件对比功能
    elif function_choice == "单文件对比":
        st.header("单文件对比")
        st.write("上传两个PDF文件，比较它们之间的文本差异")
        
        col1, col2 = st.columns(2)
        
        with col1:
            file1 = st.file_uploader("选择第一个PDF文件", type="pdf", key="file1")
        
        with col2:
            file2 = st.file_uploader("选择第二个PDF文件", type="pdf", key="file2")
        
        if file1 and file2:
            # 提取文本
            text1 = extract_text_from_pdf(file1)
            text2 = extract_text_from_pdf(file2)
            
            # 保存到会话状态
            if file1.name not in st.session_state.uploaded_files and text1:
                st.session_state.uploaded_files[file1.name] = text1
            if file2.name not in st.session_state.uploaded_files and text2:
                st.session_state.uploaded_files[file2.name] = text2
            
            # 显示比较结果
            compare_texts(text1, text2, file1.name, file2.name)
    
    # 多文件对比分析功能
    elif function_choice == "多文件对比分析":
        st.header("多文件对比分析")
        st.write("上传多个PDF文件，分析它们之间的相似度")
        
        uploaded_files = st.file_uploader(
            "选择多个PDF文件", 
            type="pdf", 
            accept_multiple_files=True,
            key="multi_files"
        )
        
        # 显示已上传的文件
        if uploaded_files:
            st.success(f"已上传 {len(uploaded_files)} 个文件")
            
            # 提取所有文件的文本
            files_dict = {}
            for file in uploaded_files:
                if file.name not in st.session_state.uploaded_files:
                    text = extract_text_from_pdf(file)
                    if text:
                        st.session_state.uploaded_files[file.name] = text
                        files_dict[file.name] = text
                else:
                    files_dict[file.name] = st.session_state.uploaded_files[file.name]
            
            # 执行多文件比较
            compare_multiple_files(files_dict)
    
    # 显示已处理的文件
    if st.session_state.uploaded_files:
        with st.sidebar.expander("已处理的文件", expanded=False):
            st.write(f"共 {len(st.session_state.uploaded_files)} 个文件")
            for filename in st.session_state.uploaded_files.keys():
                st.write(f"- {filename}")
            
            if st.button("清除已处理文件"):
                st.session_state.uploaded_files = {}
                st.experimental_rerun()

# 运行主函数
if __name__ == "__main__":
    main()
