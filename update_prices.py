import requests
import xml.etree.ElementTree as ET
import os
import time
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

# 💡 공공데이터포털의 이중 인코딩을 원천 차단하기 위해 params 방식 대신 URL 문자열 조립 방식으로 변환
SERVICE_KEY = "ed5eb4cbab5b22ea97fe39d5fbb5c3b0b27037c3bc5c1d43ed3e2f7e37d261ba"

def get_recent_price(bjd_code, apt_name, area=None):
    lawd_cd = bjd_code[:5] if bjd_code and len(bjd_code) >= 5 else None
    if not lawd_cd:
        print(f"⚠️ {apt_name}: lawd_cd 추출 실패")
        return None

    now = datetime.now()
    # 2026년 현재 시점 기준 최근 4개월 트래킹 월 배열 조립
    months_to_try = [
        (now - timedelta(days=30 * i)).strftime("%Y%m")
        for i in range(0, 4)
    ]

    for deal_ymd in months_to_try:
        try:
            # 💡 requests.get의 params를 쓰지 않고 curl처럼 완전한 URL 통문자열을 찔러서 403을 우회합니다.
            full_url = (
                f"http://apis.data.go.kr/1613000/RTMSDataSvcAptTrade/getRTMSDataSvcAptTrade"
                f"?serviceKey={SERVICE_KEY}&LAWD_CD={lawd_cd}&DEAL_YMD={deal_ymd}"
                f"&pageNo=1&numOfRows=100"
            )
            
            res = requests.get(full_url, timeout=10)
            print(f"[DEBUG HTTP] {apt_name} {deal_ymd} → 상태코드: {res.status_code}")

            if res.status_code != 200:
                continue

            # XML 바이너리 덤프 파싱
            root = ET.fromstring(res.content)
            item_list = root.findall(".//item")

            if not item_list:
                continue

            clean_name = apt_name.replace(" ", "")
            matched = []

            for item in item_list:
                item_apt = (item.findtext("aptNm") or "").replace(" ", "")
                
                # 💡 [인덕원센트럴푸르지오 완치 가드] 
                # "인덕원센트럴푸르지오" 처럼 네이버명과 국토부 공식 명칭(예: 인덕원푸르지오센트럴타운)의 순서가 바뀐 경우 처리
                is_name_matched = clean_name in item_apt or item_apt in clean_name or clean_name.replace("여의도", "") in item_apt
                
                # 예외 케이스 가드: '인덕원'과 '푸르지오' 토큰이 동시에 문자열에 포함되어 있다면 99% 동일 단지이므로 통과시킴
                if not is_name_matched and "인덕원" in apt_name and "푸르지오" in apt_name:
                    if "인덕원" in item_apt and "푸르지오" in item_apt:
                        is_name_matched = True

                if is_name_matched:
                    try:
                        if area and float(area) > 0:
                            item_area = float((item.findtext("excluUseAr") or "0").replace(",", ""))
                            if abs(item_area - float(area)) > 5:
                                continue

                        price_str = (item.findtext("dealAmount") or "0").replace(",", "").strip()
                        price = int(price_str) * 10000
                        
                        year = (item.findtext("dealYear") or "").strip()
                        month = (item.findtext("dealMonth") or "").strip().zfill(2)
                        day = (item.findtext("dealDay") or "").strip().zfill(2)
                        
                        matched.append({"price": price, "date": f"{year}{month}{day}"})
                    except Exception:
                        continue

            # 💡 [정밀 추적] 루프를 다 돌았는데도 matched가 비어있다면, 국토부가 준 실제 단지명과 면적 스펙을 터미널에 덤프합니다.
            if not matched and "인덕원" in apt_name:
                print(f"\n🚨 [인덕원 디버그] 국토부 raw 데이터 스캔 결과:")
                print(f"👉 국토부 등록 단지 목록: {list(set([(item.findtext('aptNm'), item.findtext('excluUseAr')) for item in item_list if '푸르지오' in (item.findtext('aptNm') or '')]))}\n") 

            if matched:
                # 가장 최근 실거래 날짜 순으로 정렬
                matched.sort(key=lambda x: x["date"], reverse=True)
                print(f"✅ {apt_name} [{area}㎡] → {deal_ymd} 실거래가 갱신 성공: {matched[0]['price']:,}원")
                return matched[0]["price"]

        except Exception as e:
            print(f"❌ {apt_name} {deal_ymd} 런타임 예외: {e}")
            continue

        time.sleep(0.2)  # 트래픽 과부하 방지 틱

    print(f"⚠️ {apt_name} [{area}㎡]: 최근 4개월 내 매칭되는 실거래 데이터 없음")
    return None

if __name__ == "__main__":
    from supabase import create_client
    SUPABASE_URL = os.getenv("SUPABASE_URL") or os.getenv("NEXT_PUBLIC_SUPABASE_URL")
    SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY")
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

    # Supabase에서 관심부동산(is_watchlist=True) 대상 목록 스캔
    res = supabase.table("real_estate_portfolio")\
        .select("id, name, bjd_code, area")\
        .eq("is_watchlist", True)\
        .execute()

    watch_list = res.data or []
    print(f"🚀 관심부동산 총 {len(watch_list)}건 국토부 실거래가 연동 동기화 시작\n")

    for item in watch_list:
        bjd_code = item.get("bjd_code", "")
        name = item.get("name", "")
        area_val = item.get("area") or 0

        if not bjd_code:
            print(f"⚠️ {name}: 법정동 코드(bjd_code)가 누락되어 스킵합니다.")
            continue

        price = get_recent_price(bjd_code, name, area=area_val)
        if price:
            # 국토부 실거래가 시세를 Supabase의 current_price 컬럼으로 동기화 밀어넣기
            supabase.table("real_estate_portfolio")\
                .update({"current_price": price})\
                .eq("id", item.get("id"))\
                .execute()
            print(f"💾 {name} → DB 캐시 업데이트 완료: {price:,}원\n")
        else:
            print(f"⚠️ {name} 시세 동기화 실패\n")

    print("✅ 전체 관심부동산 실거래가 동기화 배치 프로세스 완료")