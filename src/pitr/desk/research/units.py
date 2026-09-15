"""Normalize equivalent unit spellings without scaling values or guessing currencies."""
import re


def canonical_unit(unit):
    key=re.sub(r'[\s_]+','',unit).upper()
    aliases={
        'RMBMN':'RMB_mn','CNYMN':'RMB_mn','RMBMILLION':'RMB_mn',
        'USDMN':'USD_mn','US$MN':'USD_mn','USDMILLION':'USD_mn',
        'RMBBN':'RMB_bn','CNYBN':'RMB_bn','RMBBILLION':'RMB_bn',
        'USDBN':'USD_bn','US$BN':'USD_bn','USDBILLION':'USD_bn',
        'USD/ADS':'USD_per_ADS','US$/ADS':'USD_per_ADS','USDPERADS':'USD_per_ADS',
        'RMB/ADS':'RMB_per_ADS','CNY/ADS':'RMB_per_ADS','RMBPERADS':'RMB_per_ADS',
        'X':'multiple','倍':'multiple','%':'percent','PERCENT':'percent',
        'PPT':'percentage_points','PP':'percentage_points','PERCENTAGEPOINTS':'percentage_points',
    }
    return aliases.get(key,unit)
