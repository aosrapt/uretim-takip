import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, timedelta, date
import ast
import time

# --- AYARLAR ---
st.set_page_config(page_title="Online Üretim (V24)", layout="wide", page_icon="🏭")

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
        st.error(f"Bağlantı Hatası: {e}"); return None

# --- TABLO ŞEMASI ---
SCHEMA = {
    "bilesenler": ["Bilesen_Adi", "Tip"],
    "limitler": ["Hammadde", "Kritik_Limit_KG"],
    "urun_tanimlari": ["Urun_Kodu", "Urun_Adi", "Net_Paket_KG", "Raf_Omru_Ay", "Recete_Kati_JSON", "Recete_Sivi_JSON"],
    "stok_durumu": ["Stok_ID", "Tarih", "Hammadde", "Parti_No", "Giris_Miktari", "Kalan_Miktar", "Birim", "Ambalaj_Birim_Gr"],
    "uretim_loglari": ["Uretim_ID", "Tarih", "Urun_Kodu", "Uretim_Parti_No", "Uretilen_Paket", "Uretilen_Net_KG", "Fire_Kati_KG", "Fire_Sivi_KG", "Fire_Amb_KG"],
    "bitmis_urunler": ["Uretim_ID", "Urun_Kodu", "Uretim_Parti_No", "Uretim_Tarihi", "SKT", "Baslangic_Net_KG", "Kalan_Net_KG", "Paket_Agirligi"],
    "sevkiyatlar": ["Sevkiyat_ID", "Tarih", "Uretim_ID", "Musteri", "Tip", "Sevk_Edilen_KG", "Aciklama"]
}

TABS = {
    "production": "uretim_loglari", "inventory": "stok_durumu",
    "products": "urun_tanimlari", "finished_goods": "bitmis_urunler",
    "shipments": "sevkiyatlar", "limits": "limitler", "ingredients": "bilesenler"
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

def load_data(key):
    """Güvenli Veri Yükleme: Sadece şemadaki sütunları alır."""
    tab_name = TABS[key]
    expected_cols = SCHEMA[tab_name]
    ws = get_worksheet(tab_name)
    
    if ws:
        try:
            data = ws.get_all_records()
            df = pd.DataFrame(data)
            
            if df.empty: return pd.DataFrame(columns=expected_cols)
            
            # 1. Eksik sütunları tamamla
            for col in expected_cols:
                if col not in df.columns: df[col] = ""
            
            # 2. Fazla (Gereksiz) sütunları at
            df = df[expected_cols]
            
            # 3. Kritik alanları string yap
            for str_col in ["Parti_No", "Uretim_Parti_No", "Urun_Kodu", "Bilesen_Adi"]:
                if str_col in df.columns: df[str_col] = df[str_col].astype(str)
                
            return df
        except: return pd.DataFrame(columns=expected_cols)
    return pd.DataFrame(columns=expected_cols)

def clean_for_json(val):
    """Veriyi hücreye yazılabilir formata çevirir"""
    if pd.isna(val): return ""
    if isinstance(val, (datetime, date)): return val.strftime("%Y-%m-%d")
    return str(val)

def save_data(df, key):
    ws = get_worksheet(TABS[key])
    if ws:
        ws.clear()
        
        # 1. Sadece şemadaki sütunları tut (Garanti)
        tab_name = TABS[key]
        expected_cols = SCHEMA[tab_name]
        # Eğer df'de eksik sütun varsa ekle
        for c in expected_cols:
            if c not in df.columns: df[c] = ""
        # Sıralamayı ve filtrelemeyi yap
        df = df[expected_cols]
        
        # 2. Gövdeyi temizle
        df_clean = df.fillna("").applymap(clean_for_json)
        
        # 3. Başlıkları string yap (Hata Çözümü)
        headers = [str(c) for c in df_clean.columns]
        
        # 4. Yaz
        data = [headers] + df_clean.values.tolist()
        ws.update(data)

# --- FORMATLAR & RESET ---
if 'form_key' not in st.session_state: st.session_state['form_key'] = 0
if 'is_admin' not in st.session_state: st.session_state['is_admin'] = False
def reset_forms(): st.session_state['form_key'] += 1
def format_date_tr(date_obj):
    if pd.isna(date_obj) or str(date_obj)=="" or str(date_obj)=="nan": return "-"
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
        st.info("👀 Misafir Modu")
        pwd = st.text_input("Yönetici Şifresi", type="password")
        if st.button("Giriş Yap"):
            if pwd == st.secrets["admin_password"]:
                st.session_state['is_admin'] = True
                st.success("Başarılı!"); st.rerun()
            else: st.error("Hatalı Şifre!")
    else:
        st.success("🔓 Yönetici")
        if st.button("Çıkış"): st.session_state['is_admin'] = False; st.rerun()
    
    st.divider()
    
    if st.session_state['is_admin']:
        if st.button("🛠️ TABLOLARI ONAR"):
            with st.spinner("Tablolar temizleniyor..."):
                client = get_gsheet_client()
                sh = client.open(SHEET_NAME)
                for t_key, t_name in TABS.items():
                    try: ws = sh.worksheet(t_name)
                    except: ws = sh.add_worksheet(title=t_name, rows="1000", cols="20")
                    if not ws.get_all_values(): 
                        if t_name in SCHEMA: ws.append_row(SCHEMA[t_name])
                    time.sleep(0.5)
            st.success("Onarım Tamamlandı!"); time.sleep(1); st.rerun()

if st.session_state['is_admin']:
    menu_options = ["📝 Üretim Girişi", "📦 Stok & Limitler", "⚙️ Reçete & Hammadde", "🚚 Sevkiyat & Son Ürün", "🔍 İzlenebilirlik", "📊 Raporlar"]
else:
    menu_options = ["🔍 İzlenebilirlik", "📊 Raporlar", "📦 Stok Durumu (İzle)", "🚚 Son Ürün (İzle)"]

menu = st.sidebar.radio("Menü", menu_options)
f_key = st.session_state['form_key']

# --- SAYFALAR ---

if menu == "⚙️ Reçete & Hammadde":
    st.header("⚙️ Reçete & Hammadde")
    t1, t2 = st.tabs(["Ürün/Reçete", "Hammadde Ekle"])
    
    with t2:
        c1,c2 = st.columns(2)
        nn = c1.text_input("Ad", key=f"in_{f_key}"); nt = c2.selectbox("Tip", ["Katı","Sıvı","Ambalaj"], key=f"it_{f_key}")
        if st.button("Ekle", key=f"bi_{f_key}"):
            if nn and nn not in ALL_ING:
                df = load_data("ingredients")
                new_row = pd.DataFrame([[nn, nt]], columns=["Bilesen_Adi","Tip"])
                df = pd.concat([df, new_row], ignore_index=True)
                save_data(df, "ingredients")
                dfl = load_data("limits")
                dfl = pd.concat([dfl, pd.DataFrame([[nn, 0]], columns=["Hammadde","Kritik_Limit_KG"])], ignore_index=True)
                save_data(dfl, "limits")
                st.success("Eklendi"); reset_forms(); st.rerun()
        st.dataframe(df_ing_global)

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

        with st.form("pf"):
            c1,c2,c3,c4=st.columns(4)
            pc=c1.text_input("Kod", d_vals.get("Urun_Kodu"), disabled=op=="Düzenle", key=f"pc_{uid}_{f_key}")
            pn=c2.text_input("Ad", d_vals.get("Urun_Adi"), key=f"pn_{uid}_{f_key}")
            pnt=c3.number_input("Net KG", float(d_vals.get("Net_Paket_KG", 10)), key=f"pnt_{uid}_{f_key}")
            psk=c4.number_input("Raf (Ay)", int(d_vals.get("Raf_Omru_Ay", 24)), key=f"psk_{uid}_{f_key}")
            
            st.subheader("Katı %"); ns={}; tot=0.0; cls=st.columns(4)
            for i,ing in enumerate(SOLID):
                v = cls[i%4].number_input(f"{ing}", float(s_sol.get(ing,0)*100), 0.0, 100.0, 0.001, format="%.3f", key=f"s_{ing}_{uid}_{f_key}")
                ns[ing]=v/100; tot+=v
            st.caption(f"Toplam: %{tot:.3f}")
            
            st.subheader("Sıvı KG/100"); nl={}
            for l in LIQUID: nl[l] = st.number_input(f"{l}", float(s_liq.get(l,0)), key=f"l_{l}_{uid}_{f_key}")
            
            if st.form_submit_button("Kaydet"):
                if abs(tot-100)>0.001: st.error("Katı toplam %100 olmalı")
                else:
                    nr = pd.DataFrame([{"Urun_Kodu":pc, "Urun_Adi":pn, "Net_Paket_KG":pnt, "Raf_Omru_Ay":psk, "Recete_Kati_JSON":str(ns), "Recete_Sivi_JSON":str(nl)}])
                    if op=="Düzenle": prods = prods[prods["Urun_Kodu"]!=pc]
                    prods = pd.concat([prods, nr], ignore_index=True)
                    save_data(prods, "products"); st.success("OK"); reset_forms(); st.rerun()
        
        if not prods.empty:
            def pr(j,p): 
                try: return " | ".join([f"{k} ({v*100 if p else v}{'%' if p else 'kg'})" for k,v in ast.literal_eval(str(j)).items() if v>0])
                except: return "-"
            dv = prods.copy(); dv["Katı"]=dv["Recete_Kati_JSON"].apply(lambda x:pr(x,True)); dv["Sıvı"]=dv["Recete_Sivi_JSON"].apply(lambda x:pr(x,False))
            st.dataframe(dv[["Urun_Kodu","Urun_Adi","Net_Paket_KG","Katı","Sıvı"]], use_container_width=True)

elif menu == "📦 Stok & Limitler":
    st.header("📦 Stok Yönetimi")
    t1,t2,t3 = st.tabs(["Giriş", "Sil", "Limit"])
    inv = load_data("inventory"); lim = load_data("limits")
    
    with t1:
        c1,c2,c3=st.columns(3); c4,c5=st.columns(2)
        dt=c1.date_input("Tarih", key=f"sd_{f_key}")
        ing=c2.selectbox("Hammadde", ALL_ING, key=f"si_{f_key}")
        lot=c3.text_input("Parti", key=f"sl_{f_key}")
        qty=c4.number_input("KG", key=f"sq_{f_key}")
        amb=c5.number_input("Birim Gr", key=f"sa_{f_key}") if ing in PACKAGING else 0.0
        if st.button("Kaydet", key=f"bs_{f_key}"):
            sid = f"STK-{datetime.now().strftime('%Y%m%d%H%M%S')}"
            nr = pd.DataFrame([{"Stok_ID":sid, "Tarih":str(dt), "Hammadde":ing, "Parti_No":lot, "Giris_Miktari":qty, "Kalan_Miktar":qty, "Birim":"KG", "Ambalaj_Birim_Gr":amb}])
            inv = pd.concat([inv, nr], ignore_index=True); save_data(inv, "inventory")
            st.success("OK"); reset_forms(); st.rerun()
        if not inv.empty:
            inv["Kalan_Miktar"]=pd.to_numeric(inv["Kalan_Miktar"], errors='coerce')
            st.dataframe(inv[inv["Kalan_Miktar"]>0])
            
    with t2:
        if not inv.empty:
            opts = [(i, f"{r['Tarih']} {r['Hammadde']} {r['Parti_No']}") for i,r in inv.sort_values("Tarih",False).head(20).iterrows()]
            sel = st.selectbox("Seç", opts, format_func=lambda x:x[1], key="dsl")
            if st.button("Sil"): inv=inv.drop(sel[0]); save_data(inv, "inventory"); st.success("OK"); st.rerun()
            
    with t3:
        with st.form("lf"):
            upd=[]
            for i, ig in enumerate(ALL_ING):
                if not lim.empty:
                    cur_row = lim[lim["Hammadde"]==ig]
                    cur = cur_row["Kritik_Limit_KG"].sum() if not cur_row.empty else 0.0
                else: cur=0.0
                v = st.number_input(f"{ig}", float(cur))
                upd.append({"Hammadde":ig, "Kritik_Limit_KG":v})
            if st.form_submit_button("Güncelle"): save_data(pd.DataFrame(upd), "limits"); st.success("OK"); st.rerun()

elif menu == "📝 Üretim Girişi":
    st.header("📝 Üretim Kaydı")
    pro
