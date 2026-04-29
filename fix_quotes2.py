import re

filepath = r'e:\硕腾网络\PyGBSentry\ProtoForge\protoforge\api\v1\router.py'

with open(filepath, 'r', encoding='utf-8') as f:
    content = f.read()

# Fix double quotes at end of Chinese strings: "xxx"" -> "xxx"
content = re.sub(r'([\u4e00-\u9fff\u3000-\u303f\uff00-\uffef])""', r'\1"', content)

# Fix missing closing quotes before comma in dict values: "xxx, "key" -> "xxx", "key"
# Pattern: Chinese text + , + space + "key":
content = re.sub(r'([\u4e00-\u9fff\w]), ("(?:description|simple|tags|id|name|value)")', r'\1", \2', content)

with open(filepath, 'w', encoding='utf-8') as f:
    f.write(content)

print("Done")
