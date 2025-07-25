import streamlit as st
from PyPDF2 import PdfReader
from difflib import SequenceMatcher
import base64
import re
import requests
import jieba
from io import StringIO

# 页面设置和样式保持不变
st.set_page_config(
    page_title="Qwen 中文PDF条款合规性分析工具",
    page_icon="📄",
    layout="wide"
)

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

QWEN_API_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"

# 原有函数保持不变（call_qwen_api, extract_text_from_pdf等）
def call_qwen_api(prompt, api_key):
    if not api_key:
        st.error("Qwen API密钥未设置，请在左侧栏输入密钥")
        return None
        
    try:
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }
        
        data = {
            "model": "qwen-plus",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.3,
            "max_tokens": 5000
        }
        
        response = requests.post(
            QWEN_API_URL,
            headers=headers,
            json=data,
            timeout=60
        )
        
        if response.status_code != 200:
            st.error(f"API请求失败，状态码: {response.status_code}，响应: {response.text}")
            return None
            
        response_json = response.json()
        
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
    try:
        pdf_reader = PdfReader(file)
        text = ""
        for page in pdf_reader.pages:
            page_text = page.extract_text() or ""
            page_text = page_text.replace("  ", "").replace("\n", "").replace("\r", "")
            text += page_text
        return text
    except Exception as e:
        st.error(f"提取文本失败: {str(e)}")
        return ""

def split_into_clauses(text):
    patterns = [
        r'(第[一二三四五六七八九十百]+条\s+.*?)(?=第[一二三四五六七八九十百]+条\s+|$)',
        r'([一二三四五六七八九十]+、\s+.*?)(?=[一二三四五六七八九十]+、\s+|$)',
        r'(\d+\.\s+.*?)(?=\d+\.\s+|$)',
        r'(\([一二三四五六七八九十]+\)\s+.*?)(?=\([一二三四五六七八九十]+\)\s+|$)',
        r'(\([1-9]+\)\s+.*?)(?=\([1-9]+\)\s+|$)',
        r'(【[^\】]+】\s+.*?)(?=【[^\】]+】\s+|$)'
    ]
    
    for pattern in patterns:
        clauses = re.findall(pattern, text, re.DOTALL)
        if len(clauses) > 3:
            return [clause.strip() for clause in clauses if clause.strip()]
    
    paragraphs = re.split(r'[。；！？]\s*', text)
    paragraphs = [p.strip() for p in paragraphs if p.strip() and len(p) > 10]
    return paragraphs

def chinese_text_similarity(text1, text2):
    words1 = list(jieba.cut(text1))
    words2 = list(jieba.cut(text2))
    return SequenceMatcher(None, words1, words2).ratio()

def match_clauses(clauses1, clauses2):
    matched_pairs = []
    used_indices = set()
    
    for i, clause1 in enumerate(clauses1):
        best_match = None
        best_ratio = 0.25
        best_j = -1
        
        for j, clause2 in enumerate(clauses2):
            if j not in used_indices:
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

def analyze_compliance_with_qwen(clause1, clause2, filename1, filename2, api_key):
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
    prompt = f"""
    请分析以下中文条款的内容：
    
    {doc_name} 中的条款：{clause}
    
    请用中文评估该条款的主要内容、核心要求、潜在影响和可能存在的问题，
    并给出简要分析和建议。分析时请注意中文表述的准确性和专业性。
    """
    
    return call_qwen_api(prompt, api_key)

# 新增：生成分析报告文本
def generate_analysis_report(matched_pairs, unmatched1, unmatched2, 
                            filename1, filename2, api_key):
    report = []
    report.append("="*50)
    report.append(f"条款合规性分析报告")
    report.append(f"对比文件: {filename1} 与 {filename2}")
    report.append("="*50 + "\n")
    
    # 总体统计
    report.append(f"分析统计:")
    report.append(f"- {filename1} 条款总数: {len(matched_pairs) + len(unmatched1)}")
    report.append(f"- {filename2} 条款总数: {len(matched_pairs) + len(unmatched2)}")
    report.append(f"- 匹配条款对数: {len(matched_pairs)}")
    report.append(f"- {filename1} 独有条款数: {len(unmatched1)}")
    report.append(f"- {filename2} 独有条款数: {len(unmatched2)}\n")
    report.append("-"*50 + "\n")
    
    # 匹配条款分析
    report.append("一、匹配条款分析")
    report.append("-"*50)
    
    for i, (clause1, clause2, ratio) in enumerate(matched_pairs):
        report.append(f"\n匹配对 {i+1} (相似度: {ratio:.2%})")
        report.append(f"{filename1} 条款: {clause1}")
        report.append(f"{filename2} 条款: {clause2}")
        
        analysis = analyze_compliance_with_qwen(clause1, clause2, filename1, filename2, api_key)
        if analysis:
            report.append("分析结果:")
            report.append(analysis)
        report.append("-"*30)
    
    # 未匹配条款分析
    report.append("\n二、未匹配条款分析")
    report.append("-"*50)
    
    report.append(f"\n{filename1} 独有条款:")
    for i, clause in enumerate(unmatched1):
        report.append(f"\n条款 {i+1}: {clause}")
        analysis = analyze_standalone_clause_with_qwen(clause, filename1, api_key)
        if analysis:
            report.append("分析结果:")
            report.append(analysis)
        report.append("-"*30)
    
    report.append(f"\n{filename2} 独有条款:")
    for i, clause in enumerate(unmatched2):
        report.append(f"\n条款 {i+1}: {clause}")
        analysis = analyze_standalone_clause_with_qwen(clause, filename2, api_key)
        if analysis:
            report.append("分析结果:")
            report.append(analysis)
        report.append("-"*30)
    
    # 总结建议
    report.append("\n三、总结与建议")
    report.append("-"*50)
    
    summary_prompt = f"""
    基于以上对{filename1}和{filename2}的条款对比分析，请给出一份总体总结和建议，包括：
    1. 两份文件的总体合规性评估
    2. 主要冲突点汇总
    3. 整体修改建议
    4. 风险提示
    """
    summary = call_qwen_api(summary_prompt, api_key)
    if summary:
        report.append(summary)
    else:
        report.append("无法生成总结分析，请检查API连接")
    
    return "\n".join(report)

# 新增：生成下载链接
def get_download_link(text, filename):
    buffer = StringIO()
    buffer.write(text)
    buffer.seek(0)
    b64 = base64.b64encode(buffer.read().encode()).decode()
    return f'<a href="data:text/plain;base64,{b64}" download="{filename}">下载分析报告</a>'

# 主界面逻辑
def main():
    st.title("Qwen 中文PDF条款合规性分析工具")
    st.write("上传两个PDF文件，系统将自动分析条款合规性并生成报告")
    
    # 侧边栏设置
    with st.sidebar:
        st.subheader("设置")
        api_key = st.text_input("Qwen API密钥", type="password")
        auto_generate = st.checkbox("自动生成分析报告", value=True)
    
    # 文件上传
    col1, col2 = st.columns(2)
    with col1:
        file1 = st.file_uploader("上传第一个PDF文件", type="pdf", key="file1")
    with col2:
        file2 = st.file_uploader("上传第二个PDF文件", type="pdf", key="file2")
    
    # 分析按钮
    if st.button("开始分析") and file1 and file2 and api_key:
        with st.spinner("正在处理文件并生成分析报告..."):
            # 提取文本
            text1 = extract_text_from_pdf(file1)
            text2 = extract_text_from_pdf(file2)
            
            # 分割条款
            clauses1 = split_into_clauses(text1)
            clauses2 = split_into_clauses(text2)
            
            # 匹配条款
            matched_pairs, unmatched1, unmatched2 = match_clauses(clauses1, clauses2)
            
            # 生成报告
            report = generate_analysis_report(
                matched_pairs, unmatched1, unmatched2,
                file1.name, file2.name, api_key
            )
            
            # 显示报告下载链接
            st.success("分析完成！")
            st.markdown(get_download_link(report, "条款合规性分析报告.txt"), unsafe_allow_html=True)
            
            # 可选：简要展示报告内容
            with st.expander("点击查看报告预览"):
                st.text_area("报告内容", report, height=400)

if __name__ == "__main__":
    main()
