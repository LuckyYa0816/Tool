# coding: utf-8
import os
import requests
from huaweicloudsdkcore.auth.credentials import BasicCredentials
from huaweicloudsdkdns.v2.region.dns_region import DnsRegion
from huaweicloudsdkcore.exceptions import exceptions
from huaweicloudsdkdns.v2 import *

# 配置信息（建议通过 GitHub Secrets 注入）
AK = os.getenv("CLOUD_SDK_AK")
SK = os.getenv("CLOUD_SDK_SK")
ZONE_ID = os.getenv("HW_ZONE_ID")
DOMAIN = os.getenv("DOMAIN") # 例如: proxy.19990816.xyz. (注意：华为云API匹配通常需要末尾的点)

def get_best_ips():
    """获取接口数据并筛选三网最优各3个IP"""
    url = "https://bestcf.pages.dev/vvhan/ipv4.txt"
    try:
        lines = requests.get(url).text.splitlines()
    except Exception as e:
        print(f"获取 IP 接口失败: {e}")
        return {}

    ips = {"电信": [], "联通": [], "移动": []}
    for line in lines:
        if not line.strip(): continue
        parts = line.split()
        ip = parts[0].split('#')[0].split(',')[0].strip()
        
        if "电信" in line and len(ips["电信"]) < 3: ips["电信"].append(ip)
        elif "联通" in line and len(ips["联通"]) < 3: ips["联通"].append(ip)
        elif "移动" in line and len(ips["移动"]) < 3: ips["移动"].append(ip)
    return ips

def sync_dns():
    best_ips = get_best_ips()
    if not any(best_ips.values()):
        print("未获取到有效 IP，任务终止")
        return

    credentials = BasicCredentials(AK, SK)
    # 国际版通常使用 ap-southeast-1 (新加坡) 或 ap-southeast-3 (香港)
    client = DnsClient.new_builder() \
        .with_credentials(credentials) \
        .with_region(DnsRegion.value_of("ap-southeast-1")) \
        .build()

    # 华为云线路名称映射 (根据你的华为云后台线路名称调整)
    line_map = {"电信": "Dianxin", "联通": "Liantong", "移动": "Yidong"}

    try:
        # 1. 获取当前 Zone 下的所有带线路的记录
        list_req = ListRecordSetsWithLineRequest()
        list_req.zone_id = ZONE_ID
        list_response = client.list_record_sets_with_line(list_req)
        
        # 建立当前记录字典 { "Dianxin": {"id": "xxx", "records": [...] } }
        current_data = {}
        for rs in list_response.recordsets:
            if rs.name == DOMAIN and rs.type == "A":
                current_data[rs.line] = {"id": rs.id, "records": sorted(rs.records)}

        # 2. 遍历三网进行比对与更新
        for carrier, new_ips in best_ips.items():
            line_key = line_map[carrier]
            new_ips_sorted = sorted(new_ips)

            if line_key in current_data:
                record_id = current_data[line_key]["id"]
                old_ips = current_data[line_key]["records"]

                if old_ips == new_ips_sorted:
                    print(f"[{carrier}] IP 未变化，跳过更新。")
                else:
                    print(f"[{carrier}] 检测到变化: {old_ips} -> {new_ips_sorted}")
                    # 使用 UpdateRecordSetRequest 更新特定 ID 的记录集
                    update_req = UpdateRecordSetRequest()
                    update_req.zone_id = ZONE_ID
                    update_req.recordset_id = record_id
                    update_req.body = UpdateRecordSetReq(records=new_ips_sorted)
                    client.update_record_set(update_req)
            else:
                print(f"[{carrier}] 华为云后台未找到线路为 {line_key} 的 {DOMAIN} A 记录，请手动创建初始值。")

    except exceptions.ClientRequestException as e:
        print(f"请求异常: {e.error_code} - {e.error_msg}")

if __name__ == "__main__":
    sync_dns()
