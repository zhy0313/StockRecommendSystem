import sys, os, time, datetime, warnings, configparser
import pandas as pd
import concurrent.futures
from tqdm import tqdm

from pandas.tseries.offsets import CustomBusinessMonthBegin
from pandas.tseries.holiday import USFederalHolidayCalendar

cur_path = os.path.dirname(os.path.abspath(__file__))
for _ in range(2):
    root_path = cur_path[0:cur_path.rfind('/', 0, len(cur_path))]
    cur_path = root_path
sys.path.append(root_path + "/" + 'Source/FetchData/')
sys.path.append(root_path + "/" + 'Source/DataBase/')

from Fetch_Data_Stock_US_Daily import updateStockData_US, getStocksList
from DB_API import queryStock

def convert_week_based_data(df):
    weekly_data = df.resample('W').agg({
                         'open': 'first', 
                         'high': 'max',
                         'low': 'min',
                         'close': 'last',
                         'volume': 'sum'})
    weekly_data.dropna(inplace = True)
    return weekly_data

def convert_month_based_data(df):
    month_index =df.index.to_period('M')
    min_day_in_month_index = pd.to_datetime(df.set_index(month_index, append=True).reset_index(level=0).groupby(level=0)['open'].min())
    custom_month_starts = CustomBusinessMonthBegin(calendar = USFederalHolidayCalendar())
    ohlc_dict = {'open':'first','high':'max','low':'min','close': 'last','volume': 'sum'}
    mthly_data = df.resample(custom_month_starts).agg(ohlc_dict)
    mthly_data.dropna(inplace = True)
    return mthly_data

def KDJ(df):
    low_list = df['low'].rolling(center=False,window=9).min()
    low_list.fillna(value=df['low'].expanding(min_periods=1).min(), inplace=True)
    high_list = df['high'].rolling(center=False,window=9).max()
    high_list.fillna(value=df['high'].expanding(min_periods=1).max(), inplace=True)
    rsv = (df['close'] - low_list) / (high_list - low_list) * 100
    df['kdj_k'] = rsv.ewm(min_periods=0,adjust=True,ignore_na=False,com=2).mean()
    df['kdj_d'] = df['kdj_k'].ewm(min_periods=0,adjust=True,ignore_na=False,com=2).mean()
    df['kdj_j'] = 3 * df['kdj_k'] - 2 * df['kdj_d']
    return(df['kdj_k'][-1], df['kdj_d'][-1], df['kdj_j'][-1])

def judge_rule(ticker, dataset, str):
    dataset['ma5'] = dataset['close'].rolling(window=5, center=False).mean()
    dataset['ma10'] = dataset['close'].rolling(window=10, center=False).mean()
    dataset['ma20'] = dataset['close'].rolling(window=20, center=False).mean()
    dataset['ma30'] = dataset['close'].rolling(window=30, center=False).mean()
    dataset['ma60'] = dataset['close'].rolling(window=60, center=False).mean()
    df = dataset[['ma5', 'ma10', 'ma20', 'ma30', 'ma60']]
    k, d, j = KDJ(dataset)
    ma5, ma10, ma20, ma30, ma60 = df['ma5'][-1], df['ma10'][-1], df['ma20'][-1], df['ma30'][-1], df['ma60'][-1]

    fit_count = 0
    if ma5  > ma10 or (ma10 - ma5)  > ma5  / 100: fit_count += 1
    if ma10 > ma20: fit_count += 1
    if ma20 > ma30: fit_count += 1
    if ma30 > ma60: fit_count += 1
    
    #if (ma10 - ma5)  > ma5  / 100 : fit_count += 0.5
    #if (ma20 - ma10) > ma10 / 100 : fit_count += 0.5
    #if (ma30 - ma20) > ma20 / 100 : fit_count += 0.5
    #if (ma60 - ma30) > ma30 / 100 : fit_count += 0.5

    if fit_count == 4 and d < 50:
        return True

    # if fit_count >= 3 and d > 0 and d < 40 and j - d > 0 and j - d < 10:
    #     print(str, fit_count, ticker, ma5, ma10, ma20, ma30, ma60, k, d, j)
    #     return True

    return False

def get_single_stock_data(root_path, symbol):
    '''
    All data is from quandl wiki dataset
    Feature set: [Open  High    Low  Close    Volume  Ex-Dividend  Split Ratio Adj. Open  Adj. High  Adj. Low
    Adj. Close  Adj. Volume]
    '''
    # file_name = stock_folder + ticker + '.csv'
    # COLUMNS = ['Date', 'Open', 'High', 'Low', 'Close', 'Volume']
    # RENAME_COLUMNS = ['date', 'open', 'high', 'low', 'close', 'volume']

    # if os.path.exists(file_name) == False: 
    #     print("get stock: " + ticker + " failed")
    #     return pd.DataFrame()

    # df = pd.read_csv(
    #     file_name,
    #     #names=COLUMNS,
    #     skipinitialspace=True,
    #     engine='python',
    #     index_col=['Date'],
    #     #usecols=COLUMNS,
    #     parse_dates=['Date'],
    #     #skiprows=1,
    #     memory_map=True,
    #     #chunksize=300,
    # ).sort_index()
    df, lastUpdateTime = queryStock(root_path, "DB_STOCK", "SHEET_US_DAILY", symbol)
    df.index = pd.to_datetime(df.index)

    if df.empty: 
        print("empty df", symbol)
        return df

    if 'Adj Close' in df:
        close = 'Adj Close'
    else:
        close = 'Close'
    df=df.rename(columns = {'Date':'date', 'Open':'open', 'High':'high', 'Low':'low', close:'close', 'Volume':'volume'})

    return df

def inner_processing_stock_data(symbol, input_data, day_selection, week_selection, month_selection):
    # start_date = pd.Timestamp(paras.start_date)
    # end_date   = pd.Timestamp(paras.end_date)
    # input_data = input_data.loc[(input_data.index >= start_date) & (input_data.index <= end_date)]
    day_data = input_data[input_data['volume'] > 0].copy()
    week_data = convert_week_based_data(day_data)
    month_data = convert_month_based_data(day_data)

    #day_dataset = StockDataFrame.retype(day_data)
    #week_dataset = StockDataFrame.retype(week_data)
    #month_dataset = StockDataFrame.retype(month_data)

    if judge_rule(symbol, day_data, "day based"):
        day_selection.append(symbol)

    if judge_rule(symbol, week_data, "week based"):
        week_selection.append(symbol)

    if judge_rule(symbol, month_data, "month based"):
        month_selection.append(symbol)

def processing_stock_data(root_path, symbol, day_selection, week_selection, month_selection):
    startTime = time.time()
    data = get_single_stock_data(root_path, symbol)
    if data.empty: return startTime
    if len(data) < 100: return startTime
    
    inner_processing_stock_data(symbol, data, day_selection, week_selection, month_selection)

    return startTime


def process_all_stocks_data(root_path):
    symbols = getStocksList(root_path)['Symbol'].values.tolist()

    pbar = tqdm(total=len(symbols))

    day_selection = []
    week_selection = []
    month_selection = []

    # startTime = time.time()
    # for symbol in symbols:
    #     startTime = processing_stock_data(root_path, symbol, day_selection, week_selection, month_selection)
    #     outMessage = '%-*s processed in:  %.4s seconds' % (6, symbol, (time.time() - startTime))
    #     pbar.set_description(outMessage)
    #     pbar.update(1)
    # print('total processing in:  %.4s seconds' % ((time.time() - startTime)))

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        # Start the load operations and mark each future with its URL
        future_to_stock = {executor.submit(processing_stock_data, root_path, symbol, day_selection, week_selection, month_selection): symbol for symbol in symbols}
        for future in concurrent.futures.as_completed(future_to_stock):
            stock = future_to_stock[future]
            try:
                startTime = future.result()
            except Exception as exc:
                startTime = time.time()
                print('%r generated an exception: %s' % (stock, exc))
            outMessage = '%-*s processed in:  %.4s seconds' % (6, stock, (time.time() - startTime))
            pbar.set_description(outMessage)
            pbar.update(1)

    return day_selection, week_selection, month_selection


if __name__ == "__main__":
    pd.set_option('precision', 3)
    pd.set_option('display.width',1000)
    warnings.filterwarnings('ignore', category=pd.io.pytables.PerformanceWarning)

    now = datetime.datetime.now().strftime("%Y-%m-%d")

    config = configparser.ConfigParser()
    config.read(root_path + "/" + "config.ini")
    storeType = int(config.get('Setting', 'StoreType'))

    if storeType == 1:
        from Start_DB_Server import StartServer, ShutdownServer
        # start database server (async)
        thread = StartServer(root_path)
        
        # wait for db start, the standard procedure should listen to 
        # the completed event of function "StartServer"
        time.sleep(5)
    
    print("updating data...")
    updateStockData_US(root_path, "1990-01-01", now, storeType)
    
    print("Processing data...")
    day_selection, week_selection, month_selection = process_all_stocks_data(root_path)
    day_week_selection = list(set(day_selection) & set(week_selection))
    week_month_selection = list(set(week_selection) & set(month_selection))
    day_month_selection = list(set(day_selection) & set(month_selection))
    all_selection = list(set(day_week_selection) & set(week_month_selection))
    day_selection = list(set(day_selection) - set(all_selection))
    week_selection = list(set(week_selection) - set(all_selection))
    month_selection = list(set(month_selection) - set(all_selection))
    print("all_selection", len(all_selection), all_selection)
    print("day_week_selection", len(day_week_selection), day_week_selection)
    print("week_month_selection", len(week_month_selection), week_month_selection)
    print("day_month_selection", len(day_month_selection), day_month_selection)
    print("day_selection", len(day_selection), day_selection)
    print("week_selection", len(week_selection), week_selection)
    print("month_selection", len(month_selection), month_selection)

    if storeType == 1:
        # stop database server (sync)
        time.sleep(5)
        ShutdownServer()

