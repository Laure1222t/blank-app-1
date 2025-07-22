import streamlit as st
from PyPDF2 import PdfReader
from difflib import SequenceMatcher
import base64
import re
import requests
import jieba  # 用于中文分词，提高匹配精度

# 设置页面标题和图标
st.set_page_config(
    page_title="Qwen 中文PDF条款合规性分析工具",
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

# 配置Qwen API参数 - 使用指定的API链接
QWEN_API_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"

def call_qwen_api(prompt, api_key):
    """调用Qwen大模型API，使用指定的API链接"""
    if not api_key:
        st.error("Qwen API密钥未设置，请在左侧栏输入密钥")
        return None
        
    try:
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }
        
        # 构建符合API要求的请求数据
        data = {
            "model": "qwen-plus",  # 可根据需要更换为其他Qwen模型如qwen-max
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.3,
            "max_tokens": 1500
        }
        
        # 使用指定的API链接发送POST请求
        response = requests.post(
            QWEN_API_URL,
            headers=headers,
            json=data,
            timeout=60
        )
        
        # 检查HTTP响应状态
        if response.status_code != 200:
            st.error(f"API请求失败，状态码: {response.status_code}，响应: {response.text}")
            return None
            
        # 解析JSON响应
        response_json = response.json()
        
        # 检查响应结构
        if "choices" not in response_json or len(response_json["choices"]) == 0:
            st.error("API返回格式不符合预期")
            return None
            
        return response_json["choices"][0]["message"]["content"]
        
    except requests.exceptions.Timeout:
        st.error("API请求超时，请重试")
        return None
    except Exception as e:
        st.error(f"调用Qwen API失败: {str(e)}")
        return None

def extract_text_from_pdf(file):
    """从PDF提取文本，优化中文处理"""
    try:
        pdf_reader = PdfReader(file)
        text = ""
        for page in pdf_reader.pages:
            page_text = page.extract_text() or ""
            # 处理中文空格和换行问题
            page_text = page_text.replace("  ", "").replace("\n", "").replace("\r", "")
            text += page_text
        return text
    except Exception as e:
        st.error(f"提取文本失败: {str(e)}")
        return ""

def split_into_clauses(text):
    """将文本分割为条款，增强中文条款识别"""
    # 增强中文条款模式识别
    patterns = [
        # 中文条款常见格式
        r'(第[一二三四五六七八九十百]+条\s+.*?)(?=第[一二三四五六七八九十百]+条\s+|$)',  # 第一条、第二条格式
        r'([一二三四五六七八九十]+、\s+.*?)(?=[一二三四五六七八九十]+、\s+|$)',  # 一、二、三、格式
        r'(\d+\.\s+.*?)(?=\d+\.\s+|$)',  # 1. 2. 3. 格式
        r'(\([一二三四五六七八九十]+\)\s+.*?)(?=\([一二三四五六七八九十]+\)\s+|$)',  # (一) (二) 格式
        r'(\([1-9]+\)\s+.*?)(?=\([1-9]+\)\s+|$)',  # (1) (2) 格式
        r'(【[^\】]+】\s+.*?)(?=【[^\】]+】\s+|$)'  # 【标题】格式
    ]
    
    for pattern in patterns:
        clauses = re.findall(pattern, text, re.DOTALL)
        if len(clauses) > 3:  # 确保找到足够多的条款
            return [clause.strip() for clause in clauses if clause.strip()]
    
    # 按中文标点分割段落
    paragraphs = re.split(r'[。；！？]\s*', text)
    paragraphs = [p.strip() for p in paragraphs if p.strip() and len(p) > 10]  # 过滤过短内容
    return paragraphs

def chinese_text_similarity(text1, text2):
    """计算中文文本相似度，使用分词后匹配"""
    # 使用jieba进行中文分词
    words1 = list(jieba.cut(text1))
    words2 = list(jieba.cut(text2))
    
    # 计算分词后的相似度
    return SequenceMatcher(None, words1, words2).ratio()

def match_clauses(clauses1, clauses2):
    """匹配两个文档中的相似条款，优化中文匹配"""
    matched_pairs = []
    used_indices = set()
    
    for i, clause1 in enumerate(clauses1):
        best_match = None
        best_ratio = 0.25  # 降低中文匹配阈值
        best_j = -1
        
        for j, clause2 in enumerate(clauses2):
            if j not in used_indices:
                # 使用中文优化的相似度计算
                ratio = chinese_text_similarity(clause1, clause2)
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
    """使用Qwen大模型分析条款合规性，优化中文提示词"""
    # 优化中文提示词，更符合中文条款分析场景
    prompt = f"""
    请仔细分析以下两个中文条款的合规性，判断它们是否存在冲突：
    
    {filename1} 条款：{clause1}
    
    {filename2} 条款：{clause2}
    
    请按照以下结构用中文进行详细分析：
    1. 相似度评估：评估两个条款的相似程度（高/中/低）
    2. 差异点分析：详细指出两个条款在表述、范围、要求等方面的主要差异
    3. 合规性判断：判断是否存在冲突（无冲突/轻微冲突/严重冲突）
    4. 冲突原因：如果存在冲突，请具体说明冲突的原因和可能带来的影响
    5. 建议：针对发现的问题，给出专业的处理建议
    
    分析时请特别注意中文法律/合同条款中常用表述的细微差别，
    如"应当"与"必须"、"不得"与"禁止"、"可以"与"有权"等词语的区别。
    """
    
    return call_qwen_api(prompt, api_key)

def analyze_standalone_clause_with_qwen(clause, doc_name, api_key):
    """使用Qwen大模型分析独立条款（未匹配的条款）"""
    prompt = f"""
    请分析以下中文条款的内容：
    
    {doc_name} 中的条款：{clause}
    
    请用中文评估该条款的主要内容、核心要求、潜在影响和可能存在的问题，
    并给出简要分析和建议。分析时请注意中文表述的准确性和专业性。
    """
    
    return call_qwen_api(prompt, api_key)

def show_compliance_analysis(text1, text2, filename1, filename2, api_key):
    """显示合规性分析结果"""
    # 分割条款
    with st.spinner("正在分析中文条款结构..."):
        clauses1 = split_into_clauses(text1)
        clauses2 = split_into_clauses(text2)
        
        st.success(f"条款分析完成: {filename1} 识别出 {len(clauses1)} 条条款，{filename2} 识别出 {len(clauses2)} 条条款")
    
    # 匹配条款
    with st.spinner("正在匹配相似条款..."):
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
        
        with st.spinner("正在调用Qwen大模型进行中文合规性分析..."):
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
st.title("📄 Qwen 中文PDF条款合规性分析工具")
st.markdown("专为中文文档优化的智能条款合规性分析系统")

# Qwen API设置
with st.sidebar:
    st.subheader("Qwen API 设置")
    qwen_api_key = st.text_input("请输入Qwen API密钥", type="password")
    st.markdown(f"""
    提示：API密钥可以从阿里云DashScope控制台获取。
    当前使用的API端点：`{QWEN_API_URL}`
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
            st.error("无法提取文本内容，请确认PDF包含可提取的中文文本")
        else:
            show_compliance_analysis(text1, text2, file1.name, file2.name, qwen_api_key)
else:
    st.info('请上传两个PDF文件后点击"开始合规性分析"按钮')

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
    中文PDF条款合规性分析工具 | 基于Qwen大模型 | 优化中文文档处理
</div>
""", unsafe_allow_html=True)
    
