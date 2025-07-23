import streamlit as st
from PyPDF2 import PdfReader
from difflib import SequenceMatcher
import re
import requests
import jieba
import time
from functools import lru_cache

# 初始化 jieba 分词器（只初始化一次）
jieba.initialize()

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
    .clause-box { border-left: 4px solid #007bff; padding: 10px; margin: 10px 0; background-color: #f8f9fa; }
    .model-response { background-color: #f0f2f6; padding: 15px; border-radius: 5px; margin: 10px 0; }
    .comparison-section { border: 1px solid #e6e6e6; border-radius: 8px; padding: 15px; margin-bottom: 20px; }
    .progress-container { margin: 20px 0; }
</style>
""", unsafe_allow_html=True)

# 配置Qwen API参数
QWEN_API_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"

# 性能优化：设置API调用超时和重试机制
def call_qwen_api(prompt, api_key, max_retries=2):
    """调用Qwen大模型API，带重试机制"""
    if not api_key:
        st.error("Qwen API密钥未设置，请在左侧栏输入密钥")
        return None
        
    retry_count = 0
    while retry_count <= max_retries:
        try:
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}"
            }
            
            data = {
                "model": "qwen-plus",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.3,
                "max_tokens": 1500  # 减少单次响应长度，加快返回速度
            }
            
            # 缩短超时时间
            response = requests.post(
                QWEN_API_URL,
                headers=headers,
                json=data,
                timeout=20  # 超时设置为20秒
            )
            
            if response.status_code == 200:
                response_json = response.json()
                if "choices" in response_json and len(response_json["choices"]) > 0:
                    return response_json["choices"][0]["message"]["content"]
                else:
                    st.error("API返回格式不符合预期")
                    return None
            else:
                st.error(f"API请求失败，状态码: {response.status_code}")
                retry_count += 1
                if retry_count <= max_retries:
                    st.info(f"正在重试...({retry_count}/{max_retries})")
                    time.sleep(1)  # 重试前短暂等待
                
        except requests.exceptions.Timeout:
            st.error("API请求超时")
            retry_count += 1
            if retry_count <= max_retries:
                st.info(f"正在重试...({retry_count}/{max_retries})")
                time.sleep(1)
        except Exception as e:
            st.error(f"调用Qwen API失败: {str(e)}")
            return None
            
    st.error("已达到最大重试次数，无法完成API调用")
    return None

# 性能优化：添加缓存和进度提示
@st.cache_data(show_spinner=False, ttl=3600)  # 缓存1小时
def extract_text_from_pdf(file_bytes):
    """从PDF提取文本，带进度跟踪"""
    try:
        pdf_reader = PdfReader(file_bytes)
        text = ""
        total_pages = len(pdf_reader.pages)
        
        # 小文件快速处理
        if total_pages <= 5:
            for page in pdf_reader.pages:
                page_text = page.extract_text() or ""
                page_text = page_text.replace("  ", "").replace("\n", "").replace("\r", "")
                text += page_text
            return text
            
        # 大文件显示进度
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        for i, page in enumerate(pdf_reader.pages):
            page_text = page.extract_text() or ""
            page_text = page_text.replace("  ", "").replace("\n", "").replace("\r", "")
            text += page_text
            
            # 更新进度
            progress = (i + 1) / total_pages
            progress_bar.progress(progress)
            status_text.text(f"提取文本: 已完成 {i+1}/{total_pages} 页")
            time.sleep(0.01)  # 避免UI更新过于频繁
            
        # 清理进度组件
        progress_bar.empty()
        status_text.empty()
        return text
        
    except Exception as e:
        st.error(f"提取文本失败: {str(e)}")
        return ""

# 性能优化：缓存条款分割结果
@st.cache_data(show_spinner=False, ttl=3600)
def split_into_clauses(text):
    """将文本分割为条款，优化性能"""
    # 中文条款常见格式
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
            # 过滤短条款，减少后续计算量
            return [clause.strip() for clause in clauses if clause.strip() and len(clause.strip()) > 20]
    
    # 按标点分割段落
    paragraphs = re.split(r'[。；！？]\s*', text)
    return [p.strip() for p in paragraphs if p.strip() and len(p) > 20]

# 性能优化：使用lru_cache缓存相似度计算结果
@lru_cache(maxsize=10000)
def chinese_text_similarity(text1, text2):
    """计算中文文本相似度，结果缓存"""
    words1 = tuple(jieba.cut(text1))  # 转换为可哈希类型
    words2 = tuple(jieba.cut(text2))
    return SequenceMatcher(None, words1, words2).ratio()

def match_clauses(clauses1, clauses2):
    """匹配条款，优化算法减少计算量"""
    matched_pairs = []
    used_indices = set()
    len_clauses2 = len(clauses2)
    
    # 性能优化：限制最大匹配数量，避免过度计算
    max_matches = min(50, len(clauses1), len_clauses2)
    
    for i, clause1 in enumerate(clauses1):
        if len(matched_pairs) >= max_matches:
            break  # 达到最大匹配数，停止计算
            
        best_match = None
        best_ratio = 0.3  # 提高阈值，减少低相似度匹配
        best_j = -1
        checked = 0
        
        # 性能优化：限制每个条款检查的数量
        max_checks = min(15, len_clauses2 - len(used_indices))
        
        for j, clause2 in enumerate(clauses2):
            if j not in used_indices and checked < max_checks:
                ratio = chinese_text_similarity(clause1, clause2)
                if ratio > best_ratio:
                    best_ratio = ratio
                    best_match = clause2
                    best_j = j
                checked += 1
        
        if best_match:
            matched_pairs.append((clause1, best_match, best_ratio))
            used_indices.add(best_j)
    
    return matched_pairs

def analyze_compliance_with_qwen(clause1, clause2, filename1, filename2, api_key):
    """分析条款合规性，精简提示词"""
    # 精简提示词，减少模型处理时间
    prompt = f"""分析以下两个条款的合规性：
    {filename1}：{clause1[:500]}  # 限制条款长度
    {filename2}：{clause2[:500]}
    
    请简要分析：1.相似度 2.差异点 3.是否冲突 4.建议
    用简洁中文回答，控制在300字以内。"""
    
    return call_qwen_api(prompt, api_key)

def analyze_single_comparison(base_text, compare_text, base_filename, compare_filename, api_key):
    """单文件对比分析，添加进度控制"""
    # 条款提取
    with st.spinner(f"正在分析 {compare_filename} 的条款结构..."):
        base_clauses = split_into_clauses(base_text)
        compare_clauses = split_into_clauses(compare_text)
        
        st.success(f"条款分析完成: {base_filename} 识别出 {len(base_clauses)} 条，{compare_filename} 识别出 {len(compare_clauses)} 条")
    
    # 条款匹配
    with st.spinner(f"正在匹配相似条款..."):
        matched_pairs = match_clauses(base_clauses, compare_clauses)
    
    # 显示统计
    st.divider()
    col1, col2, col3 = st.columns(3)
    col1.metric(f"{base_filename} 条款数", len(base_clauses))
    col2.metric(f"{compare_filename} 条款数", len(compare_clauses))
    col3.metric("匹配条款数", len(matched_pairs))
    
    if not matched_pairs:
        st.info("未找到匹配的条款对")
        return
    
    # 分批处理匹配结果
    st.divider()
    st.subheader(f"📊 与 {compare_filename} 的条款合规性分析")
    
    batch_size = 3  # 每批处理3对条款
    total_batches = (len(matched_pairs) + batch_size - 1) // batch_size
    
    for batch_idx in range(total_batches):
        start = batch_idx * batch_size
        end = start + batch_size
        batch = matched_pairs[start:end]
        
        st.markdown(f"### 分析批次 {batch_idx + 1}/{total_batches}")
        progress_bar = st.progress(0)
        
        for i, (clause1, clause2, ratio) in enumerate(batch):
            st.markdown(f"#### 匹配条款对 {start + i + 1}（相似度: {ratio:.2%}）")
            
            col_a, col_b = st.columns(2)
            with col_a:
                st.markdown(f'<div class="clause-box"><strong>{base_filename} 条款:</strong><br>{clause1[:600]}...</div>' 
                           if len(clause1) > 600 else 
                           f'<div class="clause-box"><strong>{base_filename} 条款:</strong><br>{clause1}</div>', 
                           unsafe_allow_html=True)
            with col_b:
                st.markdown(f'<div class="clause-box"><strong>{compare_filename} 条款:</strong><br>{clause2[:600]}...</div>'
                           if len(clause2) > 600 else
                           f'<div class="clause-box"><strong>{compare_filename} 条款:</strong><br>{clause2}</div>',
                           unsafe_allow_html=True)
            
            with st.spinner(f"正在分析第 {start + i + 1} 对条款..."):
                analysis = analyze_compliance_with_qwen(clause1, clause2, base_filename, compare_filename, api_key)
            
            if analysis:
                st.markdown(f'<div class="model-response"><strong>分析结果:</strong><br>{analysis}</div>', 
                           unsafe_allow_html=True)
            
            # 更新批次进度
            progress = (i + 1) / len(batch)
            progress_bar.progress(progress)
            st.divider()
        
        progress_bar.empty()

# 主界面
st.title("📄 Qwen 中文PDF条款合规性分析工具")
st.markdown("优化版：更快的处理速度，支持一对多文件比对")

# API设置
with st.sidebar:
    st.subheader("Qwen API 设置")
    qwen_api_key = st.text_input("请输入Qwen API密钥", type="password")
    st.markdown("提示：API密钥可从阿里云DashScope控制台获取")
    
    # 性能设置
    st.subheader("性能设置")
    max_files = st.slider("最大比对文件数", 1, 5, 2)
    max_matches_per_file = st.slider("每文件最大匹配数", 5, 30, 10)

with st.form("upload_form"):
    st.subheader("文件上传区")
    base_file = st.file_uploader("选择基准PDF文件", type=["pdf"])
    compare_files = st.file_uploader("选择对比PDF文件（最多5个）", 
                                    type=["pdf"], 
                                    accept_multiple_files=True)
    
    submitted = st.form_submit_button("开始分析")

if submitted and base_file and compare_files:
    # 限制文件数量
    compare_files = compare_files[:max_files]
    
    if not qwen_api_key:
        st.warning("未检测到API密钥，分析功能将受限")
    
    try:
        # 读取基准文件（转换为字节流以便缓存）
        base_bytes = base_file.getvalue()
        base_text = extract_text_from_pdf(base_bytes)
        
        if not base_text:
            st.error("无法提取基准文件文本，请检查文件")
        else:
            # 总进度跟踪
            total_files = len(compare_files)
            overall_progress = st.progress(0)
            
            for i, compare_file in enumerate(compare_files, 1):
                st.markdown(f'## 🔍 比对分析 {i}/{total_files}: {base_file.name} vs {compare_file.name}')
                st.markdown('<div class="comparison-section">', unsafe_allow_html=True)
                
                # 处理对比文件
                compare_bytes = compare_file.getvalue()
                compare_text = extract_text_from_pdf(compare_bytes)
                
                if not compare_text:
                    st.error(f"无法提取 {compare_file.name} 的文本")
                else:
                    analyze_single_comparison(base_text, compare_text, 
                                            base_file.name, compare_file.name, 
                                            qwen_api_key)
                
                st.markdown('</div>', unsafe_allow_html=True)
                overall_progress.progress(i / total_files)
            
            overall_progress.empty()
            st.success("所有文件分析完成！")
    
    except Exception as e:
        st.error(f"应用出错: {str(e)}")
        st.exception(e)  # 显示详细错误信息用于调试
else:
    if submitted:
        if not base_file:
            st.warning("请上传基准PDF文件")
        if not compare_files:
            st.warning("请至少上传一个对比PDF文件")
    else:
        st.info('请上传文件并点击"开始分析"按钮')

# 页脚
st.divider()
st.markdown("""
<div style="text-align: center; color: #666; margin-top: 2rem;">
    中文PDF条款合规性分析工具 | 优化版
</div>
""", unsafe_allow_html=True)
