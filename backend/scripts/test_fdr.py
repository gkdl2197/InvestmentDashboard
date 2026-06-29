import FinanceDataReader as fdr

df = fdr.StockListing("KRX")

print(df.head())
print(len(df))