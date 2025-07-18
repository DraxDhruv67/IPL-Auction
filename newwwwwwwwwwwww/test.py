import pandas as pd

file_path = r"F:\new project\ipl auction\newwwwwwwwwwwww\IPLPlayerAuctionData.csv"

try:
    df = pd.read_excel(file_path, engine="openpyxl")
    print("Excel file loaded successfully!")
    print(df.head())  # Show first few rows
except Exception as e:
    print(f"Error loading file: {e}")
