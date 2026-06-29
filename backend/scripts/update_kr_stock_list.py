import os
import sys
import FinanceDataReader as fdr
from supabase import create_client
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    print("❌ .env 확인")
    sys.exit(1)

print("🚀 Supabase 연결 중...")
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

print("🔍 KRX 전체 종목 조회 중...")

try:
    df = fdr.StockListing("KRX")

    print(f"📦 총 {len(df)}개 종목 발견")

    bulk_data = []

    for _, row in df.iterrows():
        bulk_data.append({
            "symbol": str(row["Code"]).zfill(6),
            "name": row["Name"]
        })

    print("⚡ Supabase 업로드 시작...")

    batch_size = 500

    for i in range(0, len(bulk_data), batch_size):
        batch = bulk_data[i:i + batch_size]

        supabase.table("kr_stock_list") \
            .upsert(batch, on_conflict="symbol") \
            .execute()

        print(f"✅ {min(i + batch_size, len(bulk_data))}/{len(bulk_data)} 완료")

    print("🎉 모든 종목 업로드 완료!")

except Exception as e:
    print("❌ 오류:", e)