import pandas as pd
import glob

def main():
    # Find the most recent ripeness index CSV
    files = glob.glob("out/index_*.csv")
    if not files:
        print("⚠ No index CSV files found in out/")
        return

    latest = max(files, key=lambda f: f)
    print(f"Using: {latest}")

    # Load the CSV
    df = pd.read_csv(latest)

    # Show first few rows
    print("\nPreview of data:")
    print(df.head())

    # Optional: show average values per column
    print("\nColumn means:")
    print(df.mean(numeric_only=True))

if _name_ == "_main_":
    main()