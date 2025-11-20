import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from gspread_dataframe import set_with_dataframe, get_as_dataframe
from datetime import datetime, timedelta, date
import time
import ast

# --- AYARLAR ---
st.set_page_config(page_title="AACFactoryOps", layout="wide", page_icon="logo.png")

# --- GOOGLE BAĞLANTISI ---
SCOPE = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
SHEET_NAME = "Uretim_Takip_Sistemi"

@st.cache_resource
def get_gsheet_client():
    try:
        if "gcp_service_account" in st.secrets:
            creds_dict = dict(st.secrets["gcp_service_account"])
            creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, SCOPE)
        else:
            creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", SCOPE)
        return gspread.authorize(creds)
    except Exception as e:
        return None

# --- TABLO ŞEMASI ---
SCHEMA = {
    "bilesenler": ["Bilesen_Adi", "Tip"],
    "limitler": ["Hammadde", "Kritik_Limit_KG"],
    "urun_tanimlari": ["Urun_Kodu", "Urun_Adi", "Net_Paket_KG", "Raf_Omru_Ay", "Recete_Kati_JSON", "Recete_Sivi_JSON"],
    "stok_durumu": ["Stok_ID", "Tarih", "Hammadde", "Parti_No", "Giris_Miktari", "Kalan_Miktar", "Birim", "Ambalaj_Birim_Gr"],
    "uretim_loglari": ["Uretim_ID", "Tarih", "Urun_Kodu", "Uretim_Parti_No", "Uretilen_Paket", "Uretilen_Net_KG", "Fire_Kati_KG", "Fire_Sivi_KG", "Fire_Amb_KG", "Detaylar"],
    "bitmis_urunler": ["Uretim_ID", "Urun_Kodu", "Uretim_Parti_No", "Uretim_Tarihi", "SKT", "Baslangic_Net_KG", "Kalan_Net_KG", "Paket_Agirligi"],
    "sevkiyatlar": ["Sevkiyat_ID", "Tarih", "Uretim_ID", "Musteri", "Tip", "Sevk_Edilen_KG", "Aciklama"],
    "silme_loglari": ["Log_ID", "Tarih", "Tur", "Detay", "Neden"]
}

TABS = {
    "production": "uretim_loglari", "inventory": "stok_durumu",
    "products": "urun_tanimlari", "finished_goods": "bitmis_urunler",
    "shipments": "sevkiyatlar", "limits": "limitler", "ingredients": "bilesenler",
    "deletion_logs": "silme_loglari"
}

def get_worksheet(tab_name):
    client = get_gsheet_client()
    if not client: return None
    try:
        sh = client.open(SHEET_NAME)
        try: ws = sh.worksheet(tab_name)
        except: ws = sh.add_worksheet(title=tab_name, rows="1000", cols="20")
        return ws
    except: return None

# --- CACHED LOAD (HIZ VE TİP GARANTİSİ) ---
@st.cache_data(ttl=60)  # 60 saniye cache tut, sayfa yenilemelerinde hızlı çalışsın
def load_data(key):
    tab_name = TABS[key]
    ws = get_worksheet(tab_name)
    cols = SCHEMA[tab_name]
    
    if ws:
        try:
            df = get_as_dataframe(ws, evaluate_formulas=True, usecols=cols)
            # Boş satırları at
            df = df.dropna(how='all')
            
            # TİP ZORLAMA (Arrow Hatası Çözümü)
            # Sayı olması gerekenler
            numeric_cols = ["Giris_Miktari", "Kalan_Miktar", "Ambalaj_Birim_Gr", "Net_Paket_KG", "Raf_Omru_Ay", 
                            "Uretilen_Paket", "Uretilen_Net_KG", "Fire_Kati_KG", "Fire_Sivi_KG", "Fire_Amb_KG",
                            "Baslangic_Net_KG", "Kalan_Net_KG", "Paket_Agirligi", "Sevk_Edilen_KG", "Kritik_Limit_KG"]
            
            for c in df.columns:
                if c in numeric_cols:
                    # Önce string yap, virgülü noktaya çevir, sonra sayı yap, hata verirse 0.0 yap
                    df[c] = pd.to_numeric(df[c].astype(str).str.replace(",", "."), errors='coerce').fillna(0.0)
                else:
                    # Diğer her şeyi string yap ve NaN ise boşalt
                    df[c] = df[c].astype(str).replace("nan", "").replace("None", "")

            # Eksik sütun varsa ekle
            for c in cols:
                if c not in df.columns:
                    if c in numeric_cols: df[c] = 0.0
                    else: df[c] = ""
            
            return df
        except Exception as e:
            # Hata olursa boş dön ama tipleri koru
            return pd.DataFrame(columns=cols)
    return pd.DataFrame(columns=cols)

def clear_cache():
    """İşlem yapıldığında cache'i temizle ki yeni veri görünsün"""
    st.cache_data.clear()

def add_row_to_sheet(row_data, key):
    ws = get_worksheet(TABS[key])
    if ws:
        clean_row = []
        for item in row_data:
            if item is None: clean_row.append("")
            elif isinstance(item, (datetime, date)): clean_row.append(item.strftime("%Y-%m-%d"))
            else: clean_row.append(item)
        ws.append_row(clean_row, value_input_option='USER_ENTERED')

def update_cell_in_sheet(key, unique_col_name, unique_val, target_col_name, new_val):
    ws = get_worksheet(TABS[key])
    if ws:
        try:
            data = ws.get_all_records()
            df = pd.DataFrame(data)
            df[unique_col_name] = df[unique_col_name].astype(str)
            unique_val = str(unique_val)
            matches = df.index[df[unique_col_name] == unique_val].tolist()
            
            if matches:
                row_idx = matches[0] + 2
                col_idx = df.columns.get_loc(target_col_name) + 1
                ws.update_cell(row_idx, col_idx, new_val)
        except Exception as e:
            pass  # Hata olursa sessiz kal, logla istersen

# --- FORMATLAR ---
if 'form_key' not in st.session_state: st.session_state['form_key'] = 0
if 'is_admin' not in st.session_state: st.session_state['is_admin'] = False
def reset_forms(): st.session_state['form_key'] += 1
def format_date_tr(date_obj):
    if pd.isna(date_obj) or str(date_obj)=="": return "-"
    try: return pd.to_datetime(date_obj).strftime("%d/%m/%Y")
    except: return str(date_obj)

# --- GLOBAL LİSTELER ---
try:
    df_ing_global = load_data("ingredients")
    if not df_ing_global.empty:
        SOLID = df_ing_global[df_ing_global["Tip"] == "Katı"]["Bilesen_Adi"].tolist()
        LIQUID = df_ing_global[df_ing_global["Tip"] == "Sıvı"]["Bilesen_Adi"].tolist()
        PACKAGING = df_ing_global[df_ing_global["Tip"] == "Ambalaj"]["Bilesen_Adi"].tolist()
        ALL_ING = SOLID + LIQUID + PACKAGING
    else: SOLID, LIQUID, PACKAGING, ALL_ING = [], [], [], []
except: SOLID, LIQUID, PACKAGING, ALL_ING = [], [], [], []

# --- SIDEBAR ---
st.sidebar.title("🏭 Fabrika Paneli")

with st.sidebar:
    if not st.session_state['is_admin']:
        st.info("👀 Misafir")
        pwd = st.text_input("Şifre", type="password")
        if st.button("Giriş"):
            if pwd == st.secrets["admin_password"]:
                st.session_state['is_admin'] = True
                st.success("OK"); st.rerun()
            else: st.error("Hata")
    else:
        st.success("Yönetici")
        if st.button("Çıkış"): st.session_state['is_admin'] = False; st.rerun()
    st.divider()

if st.session_state['is_admin']:
    menu_options = ["📝 Üretim Girişi", "📦 Hammadde Stok", "⚙️ Reçete & Hammadde", "🚚 Sevkiyat", "📦 Son Ürün Stok", "🔍 İzlenebilirlik"]
else:
    menu_options = ["🔍 İzlenebilirlik", "📦 Hammadde Stok (İzle)", "📦 Son Ürün Stok (İzle)"]

menu = st.sidebar.radio("Menü", menu_options)
f_key = st.session_state['form_key']

# --- SAYFALAR ---

if menu == "⚙️ Reçete & Hammadde":
    st.header("⚙️ Reçete & Hammadde")
    t1, t2, t3 = st.tabs(["Ürün/Reçete", "Hammadde Ekle", "Hammadde Sil"])
    
    with t2:
        c1,c2 = st.columns(2)
        nn = c1.text_input("Ad", key=f"in_{f_key}"); nt = c2.selectbox("Tip", ["Katı","Sıvı","Ambalaj"], key=f"it_{f_key}")
        if st.button("Ekle", key=f"bi_{f_key}"):
            if nn and nn not in ALL_ING:
                add_row_to_sheet([nn, nt], "ingredients")
                add_row_to_sheet([nn, 0], "limits")
                st.success("Eklendi")
                time.sleep(1)
                clear_cache()
                reset_forms()
                st.rerun()
        st.dataframe(df_ing_global)

    with t3:
        if not df_ing_global.empty:
            sel_ing = st.selectbox("Silinecek Hammadde", df_ing_global["Bilesen_Adi"].unique())
            neden = st.text_input("Silme Nedeni")
            if st.button("Sil ve Logla"):
                # Sil
                df_ing_global = df_ing_global[df_ing_global["Bilesen_Adi"] != sel_ing]
                ws = get_worksheet("bilesenler"); ws.clear()
                ws.update([df_ing_global.columns.values.tolist()] + df_ing_global.astype(str).values.tolist())
                # Logla
                log_id = f"DEL-{datetime.now().strftime('%Y%m%d%H%M%S')}"
                log_row = [log_id, str(datetime.now()), "Hammadde", sel_ing, neden]
                add_row_to_sheet(log_row, "deletion_logs")
                clear_cache()
                st.success("Silindi ve Loglandı"); st.rerun()
        if st.session_state['is_admin']:
            del_logs = load_data("deletion_logs")
            if not del_logs.empty:
                st.subheader("Silme Logları")
                del_logs["Tarih"]=del_logs["Tarih"].apply(format_date_tr)
                st.dataframe(del_logs[["Tarih", "Tur", "Detay", "Neden"]])

    with t1:
        prods = load_data("products")
        op = st.radio("İşlem", ["Yeni", "Düzenle"], horizontal=True, key=f"op_{f_key}")
        d_vals = {"Urun_Kodu":"", "Urun_Adi":"", "Net_Paket_KG":10.0, "Raf_Omru_Ay":24}
        s_sol, s_liq = {}, {}
        uid = "new"
        
        if op=="Düzenle" and not prods.empty:
            sel = st.selectbox("Seç", prods["Urun_Kodu"].unique(), key=f"slp_{f_key}")
            row = prods[prods["Urun_Kodu"]==sel].iloc[0]
            d_vals = row.to_dict()
            try: s_sol=ast.literal_eval(str(row.get("Recete_Kati_JSON","{}"))); s_liq=ast.literal_eval(str(row.get("Recete_Sivi_JSON","{}")))
            except: pass
            uid = sel

        with st.form(key=f"pf_{f_key}"):
            c1,c2,c3,c4=st.columns(4)
            pc=c1.text_input("Kod", d_vals.get("Urun_Kodu"), disabled=op=="Düzenle", key=f"pc_{uid}_{f_key}")
            pn=c2.text_input("Ad", d_vals.get("Urun_Adi"), key=f"pn_{uid}_{f_key}")
            pnt=c3.number_input("Net KG", float(d_vals.get("Net_Paket_KG", 10)), key=f"pnt_{uid}_{f_key}")
            psk=c4.number_input("Raf (Ay)", int(d_vals.get("Raf_Omru_Ay", 24)), key=f"psk_{uid}_{f_key}")
            
            st.subheader("Katı %"); ns={}; tot=0.0; cls=st.columns(4)
            for i,ing in enumerate(SOLID):
                v = cls[i%4].number_input(f"{ing}", min_value=0.0, max_value=100.0, value=float(s_sol.get(ing,0)*100), step=0.001, format="%.3f", key=f"s_{ing}_{uid}_{f_key}_{i}")
                ns[ing]=v/100; tot+=v
            st.caption(f"Toplam: %{tot:.3f}")
            st.subheader("Sıvı KG/100"); nl={}
            for l in LIQUID: nl[l] = st.number_input(f"{l}", value=float(s_liq.get(l,0)), key=f"l_{l}_{uid}_{f_key}")
            
            if st.form_submit_button("Kaydet"):
                if abs(tot-100)>0.001: st.error("Katı toplam %100 olmalı")
                else:
                    nr = pd.DataFrame([{"Urun_Kodu":str(pc), "Urun_Adi":str(pn), "Net_Paket_KG":pnt, "Raf_Omru_Ay":psk, "Recete_Kati_JSON":str(ns), "Recete_Sivi_JSON":str(nl)}])
                    if op=="Düzenle": prods = prods[prods["Urun_Kodu"]!=str(pc)]
                    prods = pd.concat([prods, nr], ignore_index=True)
                    ws = get_worksheet("urun_tanimlari"); ws.clear()
                    ws.update([prods.columns.values.tolist()] + prods.astype(str).values.tolist())
                    clear_cache()
                    st.success("OK"); reset_forms(); st.rerun()
        
        if not prods.empty:
            # Reçete içeriklerini parse et ve sütun ekle
            prods["Katı Reçete"] = prods["Recete_Kati_JSON"].apply(lambda x: ", ".join([f"{k}: {v*100:.2f}%" for k,v in ast.literal_eval(x).items() if v > 0]))
            prods["Sıvı Reçete"] = prods["Recete_Sivi_JSON"].apply(lambda x: ", ".join([f"{k}: {v:.2f}kg/100" for k,v in ast.literal_eval(x).items() if v > 0]))
            st.dataframe(prods[["Urun_Kodu","Urun_Adi","Net_Paket_KG", "Katı Reçete", "Sıvı Reçete"]])

elif menu == "📦 Hammadde Stok":
    st.header("📦 Hammadde Stok")
    inv = load_data("inventory"); lim = load_data("limits")
    # Uyarılar
    if not inv.empty and not lim.empty:
        merged = inv.merge(lim, left_on="Hammadde", right_on="Hammadde")
        low_stock = merged[merged["Kalan_Miktar"] < merged["Kritik_Limit_KG"]]
        if not low_stock.empty:
            low_names = ', '.join(low_stock['Hammadde'].unique())
            st.warning(f"Düşük Stok Uyarısı: {low_names}")
    t1,t2,t3 = st.tabs(["Giriş", "Sil", "Limit"])
    
    with t1:
        c1,c2,c3=st.columns(3); c4,c5=st.columns(2)
        dt=c1.date_input("Tarih", key=f"sd_{f_key}")
        ing=c2.selectbox("Hammadde", ALL_ING, key=f"si_{f_key}")
        lot=c3.text_input("Parti", key=f"sl_{f_key}")
        qty=c4.number_input("KG", key=f"sq_{f_key}")
        amb=c5.number_input("Birim Gr", key=f"sa_{f_key}") if ing in PACKAGING else 0.0
        if st.button("Kaydet", key=f"bs_{f_key}"):
            sid = f"STK-{datetime.now().strftime('%Y%m%d%H%M%S')}"
            row = [sid, str(dt), ing, lot, qty, qty, "KG", amb]
            add_row_to_sheet(row, "inventory")
            clear_cache()
            st.success("OK"); reset_forms(); st.rerun()
        if not inv.empty:
            st.dataframe(inv)
            
    with t2:
        if not inv.empty:
            opts = [(i, f"{r['Tarih']} {r['Hammadde']} {r['Parti_No']}") for i,r in inv.sort_values("Tarih", ascending=False).head(20).iterrows()]
            sel = st.selectbox("Seç", opts, format_func=lambda x:x[1], key="dsl")
            neden = st.text_input("Silme Nedeni")
            if st.button("Sil ve Logla"): 
                sel_row = inv.iloc[sel[0]]
                inv=inv.drop(sel[0])
                ws = get_worksheet("stok_durumu"); ws.clear()
                ws.update([inv.columns.values.tolist()] + inv.astype(str).values.tolist())
                # Logla
                log_id = f"DEL-{datetime.now().strftime('%Y%m%d%H%M%S')}"
                log_detay = f"{sel_row['Hammadde']} - {sel_row['Parti_No']} ({sel_row['Kalan_Miktar']}kg)"
                log_row = [log_id, str(datetime.now()), "Stok", log_detay, neden]
                add_row_to_sheet(log_row, "deletion_logs")
                clear_cache()
                st.success("OK"); st.rerun()
        if st.session_state['is_admin']:
            del_logs = load_data("deletion_logs")
            if not del_logs.empty:
                st.subheader("Silme Logları")
                del_logs["Tarih"]=del_logs["Tarih"].apply(format_date_tr)
                st.dataframe(del_logs[["Tarih", "Tur", "Detay", "Neden"]])
            
    with t3:
        with st.form("lf"):
            upd=[]
            for i, ig in enumerate(ALL_ING):
                cur = 0.0
                if not lim.empty:
                    cr = lim[lim["Hammadde"]==ig]
                    if not cr.empty: cur=float(cr.iloc[0]["Kritik_Limit_KG"])
                v = st.number_input(f"{ig}", float(cur))
                upd.append({"Hammadde":ig, "Kritik_Limit_KG":v})
            if st.form_submit_button("Güncelle"): 
                ndf = pd.DataFrame(upd)
                ws = get_worksheet("limitler"); ws.clear()
                ws.update([ndf.columns.values.tolist()] + ndf.astype(str).values.tolist())
                clear_cache()
                st.success("OK"); st.rerun()

elif menu == "📝 Üretim Girişi":
    st.header("📝 Üretim Kaydı")
    prods = load_data("products"); inv = load_data("inventory")
    if prods.empty: st.warning("Önce ürün ekleyin."); st.stop()
    
    inv["Kalan_Miktar"] = pd.to_numeric(inv["Kalan_Miktar"], errors='coerce').fillna(0)
    inv["Ambalaj_Birim_Gr"] = pd.to_numeric(inv["Ambalaj_Birim_Gr"], errors='coerce').fillna(0)
    
    c1,c2,c3,c4=st.columns(4)
    pdts=c1.date_input("Tarih", key=f"pdt_{f_key}")
    psel=c2.selectbox("Ürün", prods["Urun_Kodu"].unique(), key=f"psl_{f_key}")
    curr=prods[prods["Urun_Kodu"]==psel].iloc[0]
    plot=c3.text_input("Parti", key=f"plt_{f_key}")
    ppck=c4.number_input("Paket", 0, key=f"ppk_{f_key}")
    
    nkg=ppck*float(curr["Net_Paket_KG"]); st.info(f"Hedef: {nkg} KG")
    rs=ast.literal_eval(curr["Recete_Kati_JSON"]); rl=ast.literal_eval(curr.get("Recete_Sivi_JSON","{}"))
    inp={}; tf_amb=0.0; details = []
    
    st.subheader("1. Ambalaj")
    for pt in PACKAGING:
        stk = inv[(inv["Hammadde"]==pt)&(inv["Kalan_Miktar"]>0)]
        c_a,c_b = st.columns(2)
        opts = [None]+stk.to_dict('records')
        sel = c_a.selectbox(f"{pt} Parti", opts, format_func=lambda x: "Seç..." if x is None else f"{x['Parti_No']} ({x['Kalan_Miktar']})", key=f"ap_{pt}_{f_key}")
        act = c_b.number_input(f"{pt} Adet", 0, key=f"aa_{pt}_{f_key}")
        if sel and act>0:
            ukg=sel['Ambalaj_Birim_Gr']/1000; ckg=act*ukg; tf_amb+=(act-ppck)*ukg if ppck>0 else 0
            inp[pt]=[{"qty":ckg, "lot":sel['Parti_No']}]
            details.append(f"{pt}: {sel['Parti_No']} ({ckg}kg)")
        else: inp[pt]=None
        
    st.divider(); st.subheader("2. Katı")
    acts, theos = 0.0, 0.0
    for ig in SOLID:
        rt = rs.get(ig,0)
        if rt>0:
            th = nkg*rt; theos+=th
            st.write(f"{ig} (Teorik: {th:.2f})")
            ca,cb,cc,cd=st.columns([1.5,2,1.5,2])
            a1=ca.number_input("M1", key=f"k1_{ig}_{f_key}")
            opts=inv[(inv["Hammadde"]==ig)&(inv["Kalan_Miktar"]>0)]
            lots=[str(r['Parti_No'])+f" ({r['Kalan_Miktar']})" for _,r in opts.iterrows()]
            l1=cb.selectbox("P1", ["Seç..."]+lots, key=f"kp1_{ig}_{f_key}")
            a2=cc.number_input("M2", key=f"k2_{ig}_{f_key}")
            l2=cd.selectbox("P2", ["Seç..."]+lots, key=f"kp2_{ig}_{f_key}")
            acts+=(a1+a2); en=[]
            if a1>0: en.append({"qty":a1, "lot":l1.split(" (")[0]}); details.append(f"{ig}: {l1.split(' (')[0]} ({a1}kg)")
            if a2>0: en.append({"qty":a2, "lot":l2.split(" (")[0]}); details.append(f"{ig}: {l2.split(' (')[0]} ({a2}kg)")
            inp[ig]=en
            
    st.divider(); st.subheader("3. Sıvı")
    actl, theol = 0.0, 0.0
    for lg in LIQUID:
        rq = rl.get(lg,0); th=(nkg/100)*rq; theol+=th
        st.write(f"{lg} (Teorik: {th:.2f})")
        c1,c2=st.columns(2)
        a1=c1.number_input("Fiili", key=f"lf_{lg}_{f_key}")
        opts=inv[(inv["Hammadde"]==lg)&(inv["Kalan_Miktar"]>0)]
        lots=[str(r['Parti_No'])+f" ({r['Kalan_Miktar']})" for _,r in opts.iterrows()]
        l1=c2.selectbox("Parti", ["Seç..."]+lots, key=f"lp_{lg}_{f_key}")
        actl+=a1
        if a1>0: inp[lg]=[{"qty":a1, "lot":l1.split(" (")[0]}]; details.append(f"{lg}: {l1.split(' (')[0]} ({a1}kg)")
        else: inp[lg]=[]
        
    if st.button("Kaydet", type="primary", key=f"sv_{f_key}"):
        if ppck<=0: st.error("Paket sayısı girin"); st.stop()
        err=False
        for k,v in inp.items():
            if v:
                for e in v: 
                    if e['qty']>0 and "Seç..." in e['lot']: st.error(f"{k} parti seçilmedi"); err=True
        if not err:
            uid=f"URT-{datetime.now().strftime('%Y%m%d%H%M%S')}"
            skt=pdts+timedelta(days=int(curr["Raf_Omru_Ay"]*30))
            
            log_row = [uid, str(pdts), str(psel), str(plot), ppck, nkg, acts-theos, actl-theol, tf_amb, " | ".join(details)]
            add_row_to_sheet(log_row, "production")
            
            for k,v in inp.items():
                if v:
                    for e in v:
                        update_cell_in_sheet("inventory", "Parti_No", e['lot'], "Kalan_Miktar", 
                                             inv[(inv["Hammadde"]==k) & (inv["Parti_No"]==e['lot'])]["Kalan_Miktar"].iloc[0] - e['qty'])

            fg_row = [uid, str(psel), str(plot), str(pdts), str(skt), nkg, nkg, float(curr["Net_Paket_KG"])]
            add_row_to_sheet(fg_row, "finished_goods")
            
            clear_cache()
            st.success("Kaydedildi"); reset_forms(); st.rerun()

elif menu == "🚚 Sevkiyat":
    st.header("🚚 Sevkiyat")
    t1,t2 = st.tabs(["Sevk Et", "Geçmiş"])
    fg=load_data("finished_goods"); sh=load_data("shipments")
    if not fg.empty: fg["Kalan_Net_KG"]=pd.to_numeric(fg["Kalan_Net_KG"], errors='coerce').fillna(0)
    
    with t1:
        if not fg.empty:
            act=fg[fg["Kalan_Net_KG"]>0].copy()
            if not act.empty:
                sp=st.selectbox("Ürün", act["Urun_Kodu"].unique(), key=f"sp_{f_key}")
                opts=act[act["Urun_Kodu"]==sp]
                lst=[(i, f"{r['Uretim_Parti_No']} ({r['Kalan_Net_KG']}kg)") for i,r in opts.iterrows()]
                si=st.selectbox("Parti", lst, format_func=lambda x:x[1], key=f"si_{f_key}")[0]
                sr=fg.loc[si]
                c1,c2,c3=st.columns(3)
                cu=c1.text_input("Müşteri", key=f"scu_{f_key}")
                ty=c2.selectbox("Tip", ["Satış","Numune","İmha"], key=f"sty_{f_key}")
                kg=c3.number_input(f"KG (Max {sr['Kalan_Net_KG']})", max_value=float(sr['Kalan_Net_KG']), key=f"skg_{f_key}")
                nt=st.text_input("Not", key=f"snt_{f_key}")
                if st.button("Sevk Et", key=f"sbt_{f_key}"):
                    new_val = float(sr["Kalan_Net_KG"]) - kg
                    update_cell_in_sheet("finished_goods", "Uretim_Parti_No", sr["Uretim_Parti_No"], "Kalan_Net_KG", new_val)
                    ship_row = [f"S-{datetime.now().strftime('%Y%m%d%H%M')}", str(datetime.now()), str(sr["Uretim_ID"]), cu, ty, kg, nt]
                    add_row_to_sheet(ship_row, "shipments")
                    clear_cache()
                    st.success("Kaydedildi"); reset_forms(); st.rerun()
            else: st.info("Stok yok")
    with t2:
        if not sh.empty: 
            sh["Tarih"]=sh["Tarih"].apply(format_date_tr)
            st.dataframe(sh.sort_values("Sevkiyat_ID", ascending=False))

elif menu == "📦 Son Ürün Stok":
    st.header("📦 Son Ürün Stok")
    fg=load_data("finished_goods")
    if not fg.empty: fg["Kalan_Net_KG"]=pd.to_numeric(fg["Kalan_Net_KG"], errors='coerce').fillna(0)
    
    if not fg.empty:
        v=fg[fg["Kalan_Net_KG"]>0].copy()
        urun_filter = st.selectbox("Ürün Filtresi", ["Tümü"] + sorted(v["Urun_Kodu"].unique().tolist()))
        if urun_filter != "Tümü":
            v = v[v["Urun_Kodu"] == urun_filter]
        v["Tarih"]=v["Uretim_Tarihi"].apply(format_date_tr); v["SKT"]=v["SKT"].apply(format_date_tr)
        v["Paket"]=v["Kalan_Net_KG"]/pd.to_numeric(v["Paket_Agirligi"], errors='coerce')
        st.dataframe(v[["Urun_Kodu","Uretim_Parti_No","Tarih","SKT","Kalan_Net_KG","Paket"]])

elif menu == "🔍 İzlenebilirlik":
    st.header("🔍 İzlenebilirlik")
    t1, t2 = st.tabs(["Üretim Detay&Fireler", "İzlenebilirlik"])
    
    with t1:
        prod=load_data("production")
        if not prod.empty:
            def sd(n,d): return n/d*100 if d>0 else 0
            prod["Giren"] = prod["Uretilen_Net_KG"] + prod["Fire_Kati_KG"]
            prod["Katı %"] = [sd(f,g) for f,g in zip(prod["Fire_Kati_KG"], prod["Giren"])]
            prod["Sıvı %"] = [sd(f,n) for f,n in zip(prod["Fire_Sivi_KG"], prod["Uretilen_Net_KG"])]
            prod["Amb %"] = [sd(f,n) for f,n in zip(prod["Fire_Amb_KG"], prod["Uretilen_Net_KG"])]
            prod["Amb (gr/pkt)"] = [sd(f*1000, p) for f,p in zip(prod["Fire_Amb_KG"], prod["Uretilen_Paket"])]
            
            cols=["Tarih","Urun_Kodu","Uretim_Parti_No","Uretilen_Net_KG","Fire_Kati_KG","Katı %","Fire_Sivi_KG","Sıvı %","Fire_Amb_KG","Amb %","Amb (gr/pkt)"]
            fin=[c for c in cols if c in prod.columns]
            prod["Tarih"]=prod["Tarih"].apply(format_date_tr)
            st.dataframe(prod[fin].style.format({"Katı %":"{:.2f}%","Sıvı %":"{:.2f}%","Amb %":"{:.2f}%","Fire_Kati_KG":"{:.2f}","Fire_Sivi_KG":"{:.2f}","Fire_Amb_KG":"{:.2f}","Amb (gr/pkt)":"{:.1f} gr"}))
    
    with t2:
        prod=load_data("production"); fg=load_data("finished_goods")
        if not prod.empty:
            prod["Tarih_Fmt"]=prod["Tarih"].apply(format_date_tr)
            prod["Etiket"]=prod["Uretim_Parti_No"]+" ("+prod["Tarih_Fmt"]+")"
            sel=st.selectbox("Seç", prod["Etiket"].unique())
            row=prod[prod["Etiket"]==sel].iloc[0]
            uid=str(row["Uretim_ID"])
            rel=fg[fg["Uretim_ID"]==uid]
            
            c1,c2,c3,c4=st.columns(4)
            c1.metric("Tarih", format_date_tr(row["Tarih"]))
            c2.metric("Depoda", f"{(datetime.now()-pd.to_datetime(row['Tarih'])).days} Gün")
            if not rel.empty:
                c3.metric("SKT", format_date_tr(rel.iloc[0]["SKT"]))
                c4.metric("Stok", f"{float(rel.iloc[0]['Kalan_Net_KG']):.2f} KG")
            else: c3.metric("Durum", "Silindi")
            
            if "Detaylar" in row and row["Detaylar"]:
                st.write("**Hammadde Detayları:**")
                try:
                    details = str(row["Detaylar"]).split(" | ")
                    det_data = []
                    for d in details:
                        parts = d.split(": ")
                        if len(parts) == 2:
                            ham = parts[0]
                            rest = parts[1].split(" (")
                            lot = rest[0]
                            qty = rest[1].replace(")", "")
                            det_data.append({"Hammadde": ham, "Parti": lot, "Miktar": qty})
                    st.table(pd.DataFrame(det_data))
                except: st.write(row["Detaylar"])

elif menu == "📦 Hammadde Stok (İzle)":
    st.header("📦 Hammadde Stok")
    inv = load_data("inventory")
    if not inv.empty:
        st.dataframe(inv[inv["Kalan_Miktar"] > 0][["Tarih", "Hammadde", "Parti_No", "Kalan_Miktar"]])

elif menu == "📦 Son Ürün Stok (İzle)":
    st.header("📦 Son Ürün Stok")
    fg=load_data("finished_goods")
    if not fg.empty: fg["Kalan_Net_KG"]=pd.to_numeric(fg["Kalan_Net_KG"], errors='coerce').fillna(0)
    
    if not fg.empty:
        v=fg[fg["Kalan_Net_KG"]>0].copy()
        urun_filter = st.selectbox("Ürün Filtresi", ["Tümü"] + sorted(v["Urun_Kodu"].unique().tolist()))
        if urun_filter != "Tümü":
            v = v[v["Urun_Kodu"] == urun_filter]
        v["Tarih"]=v["Uretim_Tarihi"].apply(format_date_tr); v["SKT"]=v["SKT"].apply(format_date_tr)
        v["Paket"]=v["Kalan_Net_KG"]/pd.to_numeric(v["Paket_Agirligi"], errors='coerce')
        st.dataframe(v[["Urun_Kodu","Uretim_Parti_No","Tarih","SKT","Kalan_Net_KG","Paket"]])

