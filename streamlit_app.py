import streamlit as st
from PyPDF2 import PdfReader
from difflib import SequenceMatcher
import base64
import re
import requests
import jieba
from io import StringIO
import time
import json

# 页面设置
st.set_page_config(
    page_title="PDF条款合规性分析工具",
    page_icon="📄",
    layout="wide"
)

# 自定义样式
st.markdown("""
<style>
    .stApp { max-width: 1200px; margin: 0 auto; }
    .progress-container { margin: 20px 0; }
    .status-text { color: #666; font-style: italic; }
</style>
""", unsafe_allow_html=True)

# API配置
QWEN_API_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"

# 会话状态初始化
if 'analysis_progress' not in st.session_state:
    st.session_state.analysis_progress = 0
if 'analysis_status' not in st.session_state:
    st.session_state.analysis_status = "等待开始"
if 'partial_report' not in st.session_state:
    st.session_state.partial_report = []
if 'cancelled' not in st.session_state:
    st.session_state.cancelled = False

def call_qwen_api(prompt, api_key, timeout=120):
    """调用API并增加重试机制"""
    retries = 3
    delay = 5  # 重试延迟（秒）
    
    for attempt in range(retries):
        try:
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}"
            }
            
            data = {
                "model": "qwen-plus",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.3,
                "max_tokens": 2000  # 减少单次返回长度，避免超时
            }
            
            response = requests.post(
                QWEN_API_URL,
                headers=headers,
                json=data,
                timeout=timeout
            )
            
            if response.status_code == 200:
                response_json = response.json()
                if "choices" in response_json and len(response_json["choices"]) > 0:
                    return response_json["choices"][0]["message"]["content"]
                else:
                    st.warning(f"API返回格式异常（尝试 {attempt+1}/{retries}）")
            else:
                st.warning(f"API请求失败，状态码: {response.status_code}（尝试 {attempt+1}/{retries}）")
                
        except requests.exceptions.Timeout:
            st.warning(f"API请求超时（尝试 {attempt+1}/{retries}）")
        except Exception as e:
            st.warning(f"API调用错误: {str(e)}（尝试 {attempt+1}/{retries}）")
            
        time.sleep(delay)
        delay *= 2  # 指数退避
    
    return None

def extract_text_from_pdf(file):
    """提取PDF文本"""
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

def split_into_clauses(text, max_clauses=50):
    """分割条款并限制数量，避免处理过多内容"""
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
            # 限制最大条款数，避免处理量过大
            return [clause.strip() for clause in clauses if clause.strip()][:max_clauses]
    
    paragraphs = re.split(r'[。；！？]\s*', text)
    paragraphs = [p.strip() for p in paragraphs if p.strip() and len(p) > 10]
    return paragraphs[:max_clauses]

def chinese_text_similarity(text1, text2):
    """计算中文文本相似度"""
    words1 = list(jieba.cut(text1))
    words2 = list(jieba.cut(text2))
    return SequenceMatcher(None, words1, words2).ratio()

def match_clauses(clauses1, clauses2):
    """匹配条款"""
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

def update_progress(total_steps, current_step, status):
    """更新进度条和状态文本"""
    progress = current_step / total_steps
    st.session_state.analysis_progress = progress
    st.session_state.analysis_status = status
    
    # 更新UI
    progress_bar = st.progress(progress)
    status_text = st.markdown(f"<p class='status-text'>{status}</p>", unsafe_allow_html=True)
    
    return progress_bar, status_text

def generate_analysis_report(matched_pairs, unmatched1, unmatched2, 
                            filename1, filename2, api_key):
    """生成分析报告，带进度跟踪和部分结果保存"""
    # 重置会话状态
    st.session_state.partial_report = []
    st.session_state.analysis_progress = 0
    st.session_state.cancelled = False
    
    # 计算总步骤数
    total_steps = (len(matched_pairs) + 
                  len(unmatched1) + 
                  len(unmatched2) + 1)  # +1 是总结部分
    current_step = 0
    
    # 初始化报告
    report = []
    report.append("="*50)
    report.append(f"条款合规性分析报告")
    report.append(f"对比文件: {filename1} 与 {filename2}")
    report.append(f"生成时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    report.append("="*50 + "\n")
    
    # 总体统计
    report.append(f"分析统计:")
    report.append(f"- {filename1} 条款总数: {len(matched_pairs) + len(unmatched1)}")
    report.append(f"- {filename2} 条款总数: {len(matched_pairs) + len(unmatched2)}")
    report.append(f"- 匹配条款对数: {len(matched_pairs)}")
    report.append(f"- {filename1} 独有条款数: {len(unmatched1)}")
    report.append(f"- {filename2} 独有条款数: {len(unmatched2)}\n")
    report.append("-"*50 + "\n")
    
    # 保存部分报告
    st.session_state.partial_report = report.copy()
    
    # 显示进度条
    progress_bar, status_text = update_progress(
        total_steps, current_step, "准备分析匹配条款..."
    )
    
    # 匹配条款分析（分批处理）
    report.append("一、匹配条款分析")
    report.append("-"*50)
    
    for i, (clause1, clause2, ratio) in enumerate(matched_pairs):
        # 检查是否取消
        if st.session_state.cancelled:
            report.append("\n\n分析已取消，以下是部分结果...")
            return "\n".join(report)
            
        current_step += 1
        progress_bar, status_text = update_progress(
            total_steps, current_step, 
            f"分析匹配条款 {i+1}/{len(matched_pairs)}..."
        )
        
        report.append(f"\n匹配对 {i+1} (相似度: {ratio:.2%})")
        report.append(f"{filename1} 条款: {clause1[:200]}...")  # 截断长条款
        report.append(f"{filename2} 条款: {clause2[:200]}...")
        
        # 调用API分析
        analysis = analyze_compliance_with_qwen(clause1, clause2, filename1, filename2, api_key)
        if analysis:
            report.append("分析结果:")
            report.append(analysis)
        else:
            report.append("分析结果: 无法获取有效分析（API调用失败）")
        
        report.append("-"*30)
        
        # 保存部分报告，防止中途失败丢失所有结果
        st.session_state.partial_report = report.copy()
        time.sleep(1)  # 避免API请求过于频繁

    # 未匹配条款1分析
    report.append("\n二、未匹配条款分析")
    report.append("-"*50)
    report.append(f"\n{filename1} 独有条款:")
    
    for i, clause in enumerate(unmatched1):
        if st.session_state.cancelled:
            report.append("\n\n分析已取消，以下是部分结果...")
            return "\n".join(report)
            
        current_step += 1
        progress_bar, status_text = update_progress(
            total_steps, current_step, 
            f"分析{filename1}独有条款 {i+1}/{len(unmatched1)}..."
        )
        
        report.append(f"\n条款 {i+1}: {clause[:200]}...")
        analysis = analyze_standalone_clause_with_qwen(clause, filename1, api_key)
        if analysis:
            report.append("分析结果:")
            report.append(analysis)
        else:
            report.append("分析结果: 无法获取有效分析（API调用失败）")
        
        report.append("-"*30)
        st.session_state.partial_report = report.copy()
        time.sleep(1)

    # 未匹配条款2分析
    report.append(f"\n{filename2} 独有条款:")
    
    for i, clause in enumerate(unmatched2):
        if st.session_state.cancelled:
            report.append("\n\n分析已取消，以下是部分结果...")
            return "\n".join(report)
            
        current_step += 1
        progress_bar, status_text = update_progress(
            total_steps, current_step, 
            f"分析{filename2}独有条款 {i+1}/{len(unmatched2)}..."
        )
        
        report.append(f"\n条款 {i+1}: {clause[:200]}...")
        analysis = analyze_standalone_clause_with_qwen(clause, filename2, api_key)
        if analysis:
            report.append("分析结果:")
            report.append(analysis)
        else:
            report.append("分析结果: 无法获取有效分析（API调用失败）")
        
        report.append("-"*30)
        st.session_state.partial_report = report.copy()
        time.sleep(1)

    # 总结建议
    current_step += 1
    progress_bar, status_text = update_progress(
        total_steps, current_step, "生成总体总结与建议..."
    )
    
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

def analyze_compliance_with_qwen(clause1, clause2, filename1, filename2, api_key):
    """分析条款合规性"""
    # 缩短提示词和条款长度，避免API超时
    prompt = f"""
    分析以下两个条款的合规性：
    
    {filename1} 条款：{clause1[:500]}
    {filename2} 条款：{clause2[:500]}
    
    请简要分析：
    1. 相似度（高/中/低）
    2. 主要差异
    3. 是否存在冲突
    4. 简要建议
    """
    
    return call_qwen_api(prompt, api_key)

def analyze_standalone_clause_with_qwen(clause, doc_name, api_key):
    """分析独立条款"""
    prompt = f"""
    分析以下条款：{doc_name} 中的条款：{clause[:500]}
    
    请简要评估：
    1. 主要内容
    2. 核心要求
    3. 潜在问题
    4. 简要建议
    """
    
    return call_qwen_api(prompt, api_key)

def get_download_link(text, filename):
    """生成下载链接"""
    buffer = StringIO()
    buffer.write(text)
    buffer.seek(0)
    b64 = base64.b64encode(buffer.read().encode()).decode()
    return f'<a href="data:text/plain;base64,{b64}" download="{filename}" class="btn btn-primary">下载分析报告</a>'

def main():
    st.title("PDF条款合规性分析工具")
    st.write("上传两个PDF文件，系统将分析条款合规性并生成报告")
    
    # 侧边栏设置
    with st.sidebar:
        st.subheader("设置")
        api_key = st.text_input("Qwen API密钥", type="password")
        max_clauses = st.slider("最大处理条款数量", 10, 100, 30, 
                               help="减少此数量可加快分析速度并降低失败概率")
    
    # 文件上传
    col1, col2 = st.columns(2)
    with col1:
        file1 = st.file_uploader("上传第一个PDF文件", type="pdf", key="file1")
    with col2:
        file2 = st.file_uploader("上传第二个PDF文件", type="pdf", key="file2")
    
    # 分析控制
    col1, col2 = st.columns(2)
    with col1:
        start_analysis = st.button("开始分析", disabled=not (file1 and file2 and api_key))
    with col2:
        if st.button("取消分析"):
            st.session_state.cancelled = True
    
    if start_analysis:
        try:
            with st.spinner("准备分析..."):
                # 提取文本
                text1 = extract_text_from_pdf(file1)
                text2 = extract_text_from_pdf(file2)
                
                if not text1 or not text2:
                    st.error("无法从PDF中提取文本，请检查文件是否有效")
                    return
                
                # 分割条款
                clauses1 = split_into_clauses(text1, max_clauses)
                clauses2 = split_into_clauses(text2, max_clauses)
                
                st.info(f"条款提取完成: {file1.name} 找到 {len(clauses1)} 条，{file2.name} 找到 {len(clauses2)} 条")
                
                # 匹配条款
                matched_pairs, unmatched1, unmatched2 = match_clauses(clauses1, clauses2)
            
            # 生成报告
            report = generate_analysis_report(
                matched_pairs, unmatched1, unmatched2,
                file1.name, file2.name, api_key
            )
            
            # 显示结果
            st.success("分析完成！")
            st.markdown(get_download_link(report, "条款合规性分析报告.txt"), unsafe_allow_html=True)
            
            with st.expander("查看报告预览"):
                st.text_area("报告内容", report, height=300)
                
        except Exception as e:
            st.error(f"分析过程出错: {str(e)}")
            
            # 显示已生成的部分报告
            if st.session_state.partial_report:
                st.warning("以下是已完成的部分分析结果：")
                partial_report_text = "\n".join(st.session_state.partial_report)
                st.markdown(get_download_link(partial_report_text, "部分条款分析报告.txt"), unsafe_allow_html=True)
                with st.expander("查看部分报告"):
                    st.text_area("部分报告内容", partial_report_text, height=300)

if __name__ == "__main__":
    main()
