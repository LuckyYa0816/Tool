import os
import requests
from huaweicloudsdkcore.auth.credentials import BasicCredentials
from huaweicloudsdkdns.v2.region.dns_region import DnsRegion
from huaweicloudsdkdns.v2 import DnsClient, ListRecordSetsRequest, UpdateRecordSetRequest, UpdateRecordSetReq

# 从环境变量获取配置
AK = os.getenv("HW_AK")
SK = os.getenv("HW_SK")
ZONE_ID = os.getenv("HW_ZONE_ID")
DOMAIN = os.getenv("DOMAIN")

def get_best_ips():
    url = "https://bestcf.pages.dev/vvhan/ipv4.txt"
    lines = requests.get(url).text.splitlines()
    ips = {"电信": [], "联通": [], "移动": []}
    
    for line in lines:
        if not line.strip(): continue
        # 解析文本，提取 IP
        ip = line.split()[0].split('#')[0].split(',')[0].strip()
        
        # 强制截断：三网各只保留排在最前面的 3 个最优 IP
        if "电信" in line and len(ips["电信"]) < 3: ips["电信"].append(ip)
        elif "联通" in line and len(ips["联通"]) < 3: ips["联通"].append(ip)
        elif "移动" in line and len(ips["移动"]) < 3: ips["移动"].append(ip)
        
    return ips

def update_huawei_dns(ips):
    credentials = BasicCredentials(AK, SK)
    # 华为云国际版 API 节点 (若不同请根据实际 Region 更改，如 ap-southeast-1)
    client = DnsClient.new_builder() \
        .with_credentials(credentials) \
        .with_region(DnsRegion.value_of("ap-southeast-1")) \
        .build()

    # 华为云线路名称映射
    line_map = {"电信": "Dianxin", "联通": "Liantong", "移动": "Yidong"}

    # 获取当前域名的现有解析记录
    request = ListRecordSetsRequest()
    request.zone_id = ZONE_ID
    request.name = DOMAIN
    request.type = "A"
    response = client.list_record_sets(request)
    
    existing_records = {record.line: record for record in response.recordsets}

    for carrier, new_ips in ips.items():
        if not new_ips: continue
        line_id = line_map[carrier]
        
        if line_id in existing_records:
            record = existing_records[line_id]
            current_ips = set(record.records)
            target_ips = set(new_ips)
            
            # 若新获取的 IP 与当前解析的 IP 完全一致，则跳过
            if current_ips != target_ips:
                print(f"[{carrier}] 检测到变动，正在更新为: {new_ips}")
                req_body = UpdateRecordSetReq(records=new_ips)
                update_req = UpdateRecordSetRequest(zone_id=ZONE_ID, recordset_id=record.id, body=req_body)
                client.update_record_set(update_req)
            else:
                print(f"[{carrier}] IP 无变化，跳过执行。现有记录: {current_ips}")
        else:
            print(f"[{carrier}] 未找到对应的线路记录，请先在华为云后台手动创建一条占位记录。")

if __name__ == "__main__":
    best_ips = get_best_ips()
    update_huawei_dns(best_ips)
