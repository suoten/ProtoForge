import re

filepath = r'e:\硕腾网络\PyGBSentry\ProtoForge\protoforge\api\v1\router.py'

with open(filepath, 'rb') as f:
    raw = f.read()

content = raw.decode('utf-8', errors='replace')

# Step 1: Fix all U+FFFD replacement characters
# These are corrupted Chinese chars - fix by context
corrupted_fixes = [
    # Missing closing quote before comma in dict
    (r'"([^"]*[\u4e00-\u9fff][^"]*), ("description")', r'"\1", \2'),
    (r'"([^"]*[\u4e00-\u9fff][^"]*), ("simple")', r'"\1", \2'),
    (r'"([^"]*[\u4e00-\u9fff][^"]*), ("tags")', r'"\1", \2'),
    # Double quotes at end
    (r'([\u4e00-\u9fff])""', r'\1"'),
    # \ufffd replacement chars
    ('\ufffd', ''),
]

for pattern, replacement in corrupted_fixes:
    if isinstance(pattern, str):
        content = content.replace(pattern, replacement)
    else:
        content = re.sub(pattern, replacement, content)

# Step 2: Fix specific known broken patterns
specific_fixes = {
    # The demo message
    '"演示数据已创建：4个设+ 1个场}': '"演示数据已创建：4个设备 + 1个场景"}',
    '4个设+ 1个场': '4个设备 + 1个场景',
    # Missing closing quotes in assertion types
    '"请求应成功, "description"': '"请求应成功", "description"',
    '"值不应为空, "description"': '"值不应为空", "description"',
    '"验证返回值非空, "simple"': '"验证返回值非空", "simple"',
    '"验证值等于期望值, "description"': '"验证值等于期望值", "description"',
    '"应包含, "description"': '"应包含", "description"',
    '"验证数值大于阈值, "description"': '"验证数值大于阈值", "description"',
    '"验证数值小于阈值, "description"': '"验证数值小于阈值", "description"',
    '"值不应等于, "description"': '"值不应等于", "description"',
    '"验证值不等于指定值, "description"': '"验证值不等于指定值", "description"',
    '"验证不包含指定内容, "description"': '"验证不包含指定内容", "description"',
    '"验证匹配正则表达式, "description"': '"验证匹配正则表达式", "description"',
    '"JSON路径取值, "description"': '"JSON路径取值", "description"',
    '"从JSON中提取值验证, "description"': '"从JSON中提取值验证", "description"',
    '"类型检查, "description"': '"类型检查", "description"',
    '"验证列表长度等于指定值, "description"': '"验证列表长度等于指定值", "description"',
    '"验证列表长度小于指定值, "description"': '"验证列表长度小于指定值", "description"',
    # Test step names with missing closing quotes
    'name=f"验证场景': 'name=f"验证场景',
    'name=f"验证协议': 'name=f"验证协议',
    # Quick test strings
    'name="基础连通性测试"': 'name="基础连通性测试"',
    'name="API健康检查"': 'name="API健康检查"',
    'run_test_suite("一键测试"': 'run_test_suite("一键测试"',
    '"读写功能"': '"读写功能"',
    '"连通性"': '"连通性"',
    '"先测试API连通性"': '"先测试API连通性"',
    '"实例化模板"': '"实例化模板"',
    '"断言值"': '"断言值"',
    # template_id and name
    'template_id name 为必填项': 'template_id 和 name 为必填项',
    '模板不存在: ': '模板不存在: ',
    # Log clear
    '"日志已清空"': '"日志已清空"',
}

for old, new in specific_fixes.items():
    content = content.replace(old, new)

with open(filepath, 'w', encoding='utf-8') as f:
    f.write(content)

print("Step 1: Encoding fixes applied")

# Verify compilation
import py_compile
try:
    py_compile.compile(filepath, doraise=True)
    print("Compilation OK!")
except py_compile.PyCompileError as e:
    print(f"Compilation FAILED: {e}")
