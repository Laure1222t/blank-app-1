import streamlit as st
from PyPDF2 import PdfReader
from difflib import SequenceMatcher
import base64
import re
import json
import requests  # 用于调用Qwen API

# 设置页面标题和图标
st.set_page_config(
    page_title="Qwen PDF条款合规性分析工具",
    page_icon="📄",
    layout="wide"
)

# 自定义CSS样式
st.markdown("""
<style>
    .stApp { max-width: 1200px; margin: 0 auto; }
    .stFileUploader { width: 100%; }
    .highlight-conflict { background-color: #ffeeba; padding: 2px 4px; border-radius: 3px; }
    .clause-box { border-left: 4px solid #007bff; padding: 10px; margin: 10px 0; background-color: #f8f9fa; }
    .compliance-ok { border-left: 4px solid #28a745; }
    .compliance-warning { border-left: 4px solid #ffc107; }
    .compliance-conflict { border-left: 4px solid #dc3545; }
    .model-response { background-color: #f0f2f6; padding: 15px; border-radius: 5px; margin: 10px 0; }
</style>
""", unsafe_allow_html=True)

# Qwen大模型API调用函数
def call_qwen_api(prompt, api_key, base_url="https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"):
    """调用Qwen大模型API"""
    try:
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }
        
        data = {
            "model": "qwen-plus",  # 可以根据需要更换为其他Qwen模型
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.3,  # 降低随机性，使结果更稳定
            "max_tokens": 1024
        }
        
        response = requests.post(base_url, headers=headers, json=data, timeout=30)
        response.raise_for_status()  # 抛出HTTP错误
        return response.json()["choices"][0]["message"]["content"]
    except Exception as e:
        st.error(f"调用Qwen API失败: {str(e)}")
        return None

def extract_text_from_pdf(file):
    """从PDF提取文本"""
    try:
        pdf_reader = PdfReader(file)
        text = ""
        for page in pdf_reader.pages:
            text += page.extract_text() or ""
        return text
    except Exception as e:
        st.error(f"提取文本失败: {str(e)}")
        return ""

def split_into_clauses(text):
    """将文本分割为条款"""
    patterns = [
        r'(\d+\.\s+.*?)(?=\d+\.\s+|$)',  # 1. 2. 3. 格式
        r'([一二三四五六七八九十]+、\s+.*?)(?=[一二三四五六七八九十]+、\s+|$)',  # 一、二、三、格式
        r'((?:第)?[一二三四五六七八九十]+条\s+.*?)(?=(?:第)?[一二三四五六七八九十]+条\s+|$)',  # 第一条 格式
        r'(\([1-9]+\)\s+.*?)(?=\([1-9]+\)\s+|$)'  # (1) (2) (3) 格式
    ]
    
    for pattern in patterns:
        clauses = re.findall(pattern, text, re.DOTALL)
        if len(clauses) > 3:
            return [clause.strip() for clause in clauses if clause.strip()]
    
    # 按段落分割
    paragraphs = [p.strip() for p in text.split('\n\n') if p.strip()]
    return paragraphs

def match_clauses(clauses1, clauses2):
    """匹配两个文档中的相似条款"""
    matched_pairs = []
    used_indices = set()
    
    for i, clause1 in enumerate(clauses1):
        best_match = None
        best_ratio = 0.3
        best_j = -1
        
        for j, clause2 in enumerate(clauses2):
            if j not in used_indices:
                ratio = SequenceMatcher(None, clause1, clause2).ratio()
                if ratio > best_ratio:
                    best_ratio = ratio
                    best_match = clause2
                    best_j = j
        
        if best_match:
            matched_pairs.append((clause1, best_match, best_ratio))
            used_indices.add(best_j)
    
    unmatched1 = [clause for i, clause in enumerate(clauses1) 
                 if i not in [idx for idx, _ in enumerate(matched_pairs)]]
    unmatched2 = [clause for j, clause in enumerate(clauses2) if j not in used_indices]
    
    return matched_pairs, unmatched1, unmatched2

def create_download_link(content, filename, text):
    """生成下载链接"""
    b64 = base64.b64encode(content.encode()).decode()
    return f'<a href="data:file/txt;base64,{b64}" download="{filename}">{text}</a>'

def analyze_compliance_with_qwen(clause1, clause2, filename1, filename2, api_key):
    """使用Qwen大模型分析条款合规性"""
    if not api_key:
        st.error("请先设置Qwen API密钥")
        return None
    
    prompt = f"""
    请分析以下两个条款的合规性，判断它们是否存在冲突：
    
    {filename1} 条款：{clause1}
    
    {filename2} 条款：{clause2}
    
    请按照以下结构进行分析：
    1. 相似度评估：评估两个条款的相似程度（高/中/低）
    2. 差异点分析：指出两个条款的主要差异
    3. 合规性判断：判断是否存在冲突（无冲突/轻微冲突/严重冲突）
    4. 冲突原因：如果存在冲突，请说明冲突的具体原因
    5. 建议：针对发现的问题，给出处理建议
    
    请用中文详细回答，确保分析专业、准确。
    """
    
    return call_qwen_api(prompt, api_key)

def analyze_standalone_clause_with_qwen(clause, doc_name, api_key):
    """使用Qwen大模型分析独立条款（未匹配的条款）"""
    if not api_key:
        return None
    
    prompt = f"""
    请分析以下条款的内容：
    
    {doc_name} 中的条款：{clause}
    
    请评估该条款的主要内容、潜在影响和可能存在的问题，
    并给出简要分析和建议。
    """
    
    return call_qwen_api(prompt, api_key)

def show_compliance_analysis(text1, text2, filename1, filename2, api_key):
    """显示合规性分析结果"""
    # 分割条款
    with st.spinner("正在分析条款结构..."):
        clauses1 = split_into_clauses(text1)
        clauses2 = split_into_clauses(text2)
        
        st.success(f"条款分析完成: {filename1} 识别出 {len(clauses1)} 条条款，{filename2} 识别出 {len(clauses2)} 条条款")
    
    # 匹配条款
    with st.spinner("正在匹配条款..."):
        matched_pairs, unmatched1, unmatched2 = match_clauses(clauses1, clauses2)
    
    # 显示总体统计
    st.divider()
    col1, col2, col3 = st.columns(3)
    col1.metric(f"{filename1} 条款数", len(clauses1))
    col2.metric(f"{filename2} 条款数", len(clauses2))
    col3.metric("匹配条款数", len(matched_pairs))
    
    # 显示条款对比和合规性分析
    st.divider()
    st.subheader("📊 条款合规性详细分析（Qwen大模型）")
    
    # 分析每个匹配对的合规性
    for i, (clause1, clause2, ratio) in enumerate(matched_pairs):
        st.markdown(f"### 匹配条款对 {i+1}（相似度: {ratio:.2%}）")
        
        col_a, col_b = st.columns(2)
        with col_a:
            st.markdown(f'<div class="clause-box"><strong>{filename1} 条款:</strong><br>{clause1}</div>', unsafe_allow_html=True)
        with col_b:
            st.markdown(f'<div class="clause-box"><strong>{filename2} 条款:</strong><br>{clause2}</div>', unsafe_allow_html=True)
        
        with st.spinner("正在调用Qwen大模型进行合规性分析..."):
            analysis = analyze_compliance_with_qwen(clause1, clause2, filename1, filename2, api_key)
        
        if analysis:
            st.markdown('<div class="model-response"><strong>Qwen大模型分析结果:</strong><br>' + analysis + '</div>', unsafe_allow_html=True)
        
        st.divider()
    
    # 未匹配的条款分析
    st.subheader("未匹配条款分析")
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown(f"#### {filename1} 中独有的条款 ({len(unmatched1)})")
        for i, clause in enumerate(unmatched1):
            st.markdown(f'<div class="clause-box"><strong>条款 {i+1}:</strong><br>{clause}</div>', unsafe_allow_html=True)
            
            with st.spinner("Qwen大模型正在分析此条款..."):
                analysis = analyze_standalone_clause_with_qwen(clause, filename1, api_key)
            
            if analysis:
                st.markdown('<div class="model-response"><strong>Qwen分析:</strong><br>' + analysis + '</div>', unsafe_allow_html=True)
            st.divider()
    
    with col2:
        st.markdown(f"#### {filename2} 中独有的条款 ({len(unmatched2)})")
        for i, clause in enumerate(unmatched2):
            st.markdown(f'<div class="clause-box"><strong>条款 {i+1}:</strong><br>{clause}</div>', unsafe_allow_html=True)
            
            with st.spinner("Qwen大模型正在分析此条款..."):
                analysis = analyze_standalone_clause_with_qwen(clause, filename2, api_key)
            
            if analysis:
                st.markdown('<div class="model-response"><strong>Qwen分析:</strong><br>' + analysis + '</div>', unsafe_allow_html=True)
            st.divider()

# 应用主界面
st.title("📄 Qwen PDF条款合规性分析工具")
st.markdown("基于阿里云Qwen大模型的智能条款合规性分析")

# Qwen API设置
with st.sidebar:
    st.subheader("Qwen API 设置")
    qwen_api_key = st.text_input("请输入Qwen API密钥", type="password")
    st.markdown("""
    提示：API密钥可以从阿里云DashScope控制台获取。
    若无API密钥，可先在左侧输入框中填写以使用工具。
    """)

with st.form("upload_form"):
    col1, col2 = st.columns(2)
    with col1:
        file1 = st.file_uploader("选择第一个PDF文件（基准文档）", type=["pdf"])
    with col2:
        file2 = st.file_uploader("选择第二个PDF文件（对比文档）", type=["pdf"])
    
    submitted = st.form_submit_button("开始合规性分析")

if submitted and file1 and file2:
    if not qwen_api_key:
        st.warning("未检测到Qwen API密钥，部分功能可能受限")
    
    with st.spinner("正在解析PDF内容，请稍候..."):
        text1 = extract_text_from_pdf(file1)
        text2 = extract_text_from_pdf(file2)
        
        if not text1 or not text2:
            st.error("无法提取文本内容，请确认PDF包含可提取的文本")
        else:
            show_compliance_analysis(text1, text2, file1.name, file2.name, qwen_api_key)
else:
    st.info('请上传两个PDF文件后点击"开始合规性分析"按钮')

# 添加使用说明
with st.expander("使用说明"):
    st.markdown("""
    1. 在左侧栏输入您的Qwen API密钥
    2. 上传两个需要对比的PDF文件（建议先上传基准文档）
    3. 点击"开始合规性分析"按钮
    4. 系统会自动识别条款并调用Qwen大模型进行专业分析
    5. 查看AI生成的合规性分析结果
    
    工具优势：
    - 利用Qwen大模型的理解能力，提供更专业的合规性判断
    - 不仅指出差异，还能分析差异背后的合规性问题
    - 对未匹配的条款也能进行独立分析
    - 提供针对性的处理建议
    
    注意：API调用可能会产生费用，请参考阿里云DashScope的定价标准。
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
    Qwen PDF条款合规性分析工具 | 基于阿里云Qwen大模型 | 数据不会保留在服务器
</div>
""", unsafe_allow_html=True)
    
