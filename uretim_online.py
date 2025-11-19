import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, timedelta
import ast
import json

# --- AYARLAR ---
st.set_page_config(page_title="Online Üretim Sistemi", layout="wide", page_icon="☁️")

# --- GOOGLE SHEETS BAĞLANTISI (BULUT UYUMLU) ---
SCOPE = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
SHEET_NAME = "Uretim_Takip_Sistemi"

@st.cache_resource
def get_gsheet_client():
    try:
        # 1. Önce Buluttaki Gizli Kasaya (Secrets) Bak
        if "gcp_service_account" in st.secrets:
            creds_dict = dict(st.secrets["gcp_service_account"])
            creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, SCOPE)
        # 2. Yoksa Bilgisayardaki Dosyaya Bak (Local)
        else:
            creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", SCOPE)
            
        client = gspread.authorize(creds)
        return client
    except Exception as e:
        st.error(f"Bağlantı Hatası: {e}")
        return None

def get_worksheet(tab_name):
    client = get_gsheet_client()
    if not client: return None
    try:
        sh = client.open(SHEET_NAME)
        try:
            ws = sh.worksheet(tab_name)
        except:
            ws = sh.add_worksheet(title=tab_name, rows="100", cols="20")
        return ws
    except Exception as e:
        st.error(f"Tablo Bulunamadı: {e}. Google Drive'da '{SHEET_NAME}' tablosunu oluşturup paylaştınız mı?")
        return None

# --- VERİ YÖNETİMİ ---
TABS = {
    "production": "uretim_loglari",
    "inventory": "stok_durumu",
    "products": "urun_tanimlari",
    "finished_goods": "bitmis_urunler",
    "shipments": "sevkiyatlar",
    "limits": "limitler",
    "ingredients": "bilesenler"
}

def load_data(key):
    ws = get_worksheet(TABS[key])
    if ws:
        data = ws.get_all_records()
        df = pd.DataFrame(data)
        if "Parti_No" in df.columns: df["Parti_No"] = df["Parti_No"].astype(str)
        if "Uretim_Parti_No" in df.columns: df["Uretim_Parti_No"] = df["Uretim_Parti_No"].astype(str)
        return df
    return pd.DataFrame()

def save_data(df, key):
    ws = get_worksheet(TABS[key])
    if ws:
        ws.clear()
        df = df.fillna("")
        data_to_write = [df.columns.values.tolist()] + df.astype(str).values.tolist()
        ws.update(data_to_write)

# --- OTURUM YÖNETİMİ ---
if 'form_key' not in st.session_state: st.session_state['form_key'] = 0
def reset_forms(): st.session_state['form_key'] += 1

def format_date_tr(date_obj):
    if pd.isna(date_obj) or str(date_obj) == "": return "-"
    try: return pd.to_datetime(date_obj).strftime("%d/%m/%Y")
    except: return str(date_obj)

def init_online_system():
    # Sadece tablolara erişimi test et, oluşturma manuel yapılacak
    pass 

# --- GLOBAL LİSTELER ---
df_ing_global = load_data("ingredients")
if not df_ing_global.empty:
    SOLID_INGREDIENTS = df_ing_global[df_ing_global["Tip"] == "Katı"]["Bilesen_Adi"].tolist()
    LIQUID_INGREDIENTS = df_ing_global[df_ing_global["Tip"] == "Sıvı"]["Bilesen_Adi"].tolist()
    PACKAGING_LIST = df_ing_global[df_ing_global["Tip"] == "Ambalaj"]["Bilesen_Adi"].tolist()
    ALL_INGREDIENTS = SOLID_INGREDIENTS + LIQUID_INGREDIENTS + PACKAGING_LIST
else:
    SOLID_INGREDIENTS, LIQUID_INGREDIENTS, PACKAGING_LIST, ALL_INGREDIENTS = [], [], [], []

# --- UYARI SİSTEMİ ---
inv_check = load_data("inventory")
lim_check = load_data("limits")
alerts = []
if not inv_check.empty and not lim_check.empty:
    inv_check["Kalan_Miktar"] = pd.to_numeric(inv_check["Kalan_Miktar"], errors='coerce').fillna(0)
    lim_check["Kritik_Limit_KG"] = pd.to_numeric(lim_check["Kritik_Limit_KG"], errors='coerce').fillna(0)
    stock_sums = inv_check.groupby("Hammadde")["Kalan_Miktar"].sum()
    for idx, row in lim_check.iterrows():
        h_name = row["Hammadde"]
        limit = row["Kritik_Limit_KG"]
        if limit > 0 and stock_sums.get(h_name, 0) < limit:
            alerts.append(f"⚠️ **{h_name}** Kritik Seviyede!")

# --- ARAYÜZ ---
st.sidebar.title("🏭 Üretim (Online V16)")
if alerts: st.error("\n".join(alerts))

menu = st.sidebar.radio("Menü", [
    "📝 Üretim Girişi", 
    "📦 Hammadde Stok & Limitler", 
    "⚙️ Reçete Ekleme/Düzenleme",
    "🚚 Sevkiyat & Son Ürün", 
    "🔍 İzlenebilirlik",
    "📊 Raporlar"
])

f_key = st.session_state['form_key']

# --- 1. REÇETE ---
if menu == "⚙️ Reçete Ekleme/Düzenleme":
    st.header("⚙️ Reçete ve Hammadde")
    tab_prod, tab_ing = st.tabs(["Ürün & Reçete", "Hammadde Ekle"])
    
    with tab_ing:
        c1, c2 = st.columns(2)
        new_name = c1.text_input("Adı", key=f"ing_n_{f_key}")
        new_type = c2.selectbox("Tipi", ["Katı", "Sıvı", "Ambalaj"], key=f"ing_t_{f_key}")
        if st.button("Ekle", key=f"btn_ing_{f_key}"):
            if new_name and new_name not in ALL_INGREDIENTS:
                df = load_data("ingredients")
                new_row = pd.DataFrame([[new_name, new_type]], columns=["Bilesen_Adi", "Tip"])
                df = pd.concat([df, new_row], ignore_index=True)
                save_data(df, "ingredients")
                # Limit de ekle
                dfl = load_data("limits")
                dfl = pd.concat([dfl, pd.DataFrame([[new_name, 0]], columns=["Hammadde", "Kritik_Limit_KG"])], ignore_index=True)
                save_data(dfl, "limits")
                st.success("Eklendi"); reset_forms(); st.rerun()
        st.dataframe(df_ing_global)

    with tab_prod:
        products = load_data("products")
        op_type = st.radio("İşlem", ["Yeni Ekle", "Düzenle"], horizontal=True, key=f"op_{f_key}")
        default_vals = {"Urun_Kodu": "", "Urun_Adi": "", "Net_Paket_KG": 10.0, "Raf_Omru_Ay": 24}
        saved_solid, saved_liquid = {}, {}
        u_sfx = "new"

        if op_type == "Düzenle" and not products.empty:
            sel_code = st.selectbox("Ürün Seç", products["Urun_Kodu"].unique(), key=f"sel_p_{f_key}")
            row = products[products["Urun_Kodu"] == sel_code].iloc[0]
            default_vals = row.to_dict()
            try:
                saved_solid = ast.literal_eval(str(row.get("Recete_Kati_JSON", "{}")))
                saved_liquid = ast.literal_eval(str(row.get("Recete_Sivi_JSON", "{}")))
            except: pass
            u_sfx = sel_code

        with st.form("prod_f"):
            c1, c2, c3, c4 = st.columns(4)
            p_code = c1.text_input("Kod", value=default_vals.get("Urun_Kodu"), disabled=op_type=="Düzenle", key=f"pc_{u_sfx}_{f_key}")
            p_name = c2.text_input("Ad", value=default_vals.get("Urun_Adi"), key=f"pn_{u_sfx}_{f_key}")
            p_net = c3.number_input("Net Paket KG", value=float(default_vals.get("Net_Paket_KG", 10.0)), key=f"pnt_{u_sfx}_{f_key}")
            p_skt = c4.number_input("Raf Ömrü", value=int(default_vals.get("Raf_Omru_Ay", 24)), key=f"psk_{u_sfx}_{f_key}")
            
            st.subheader("Katı Reçete (%)")
            new_solid = {}
            cols = st.columns(4)
            tot = 0.0
            for idx, ing in enumerate(SOLID_INGREDIENTS):
                val = saved_solid.get(ing, 0.0) * 100
                n_val = cols[idx%4].number_input(f"{ing} %", value=float(val), step=0.001, format="%.3f", key=f"s_{ing}_{u_sfx}_{f_key}")
                new_solid[ing] = n_val/100
                tot += n_val
            st.caption(f"Toplam: %{tot:.3f}")
            
            st.subheader("Sıvı (KG/100KG)")
            new_liquid = {}
            for l in LIQUID_INGREDIENTS:
                v = saved_liquid.get(l, 0.0)
                new_liquid[l] = st.number_input(f"{l}", value=float(v), key=f"l_{l}_{u_sfx}_{f_key}")
            
            if st.form_submit_button("Kaydet"):
                if abs(tot - 100.0) > 0.001: st.error(f"Toplam %100 olmalı ({tot})")
                else:
                    new_row = pd.DataFrame([{"Urun_Kodu": p_code, "Urun_Adi": p_name, "Net_Paket_KG": p_net, "Raf_Omru_Ay": p_skt, "Recete_Kati_JSON": str(new_solid), "Recete_Sivi_JSON": str(new_liquid)}])
                    if op_type=="Düzenle": products = products[products["Urun_Kodu"]!=p_code]
                    products = pd.concat([products, new_row], ignore_index=True)
                    save_data(products, "products")
                    st.success("Kaydedildi"); reset_forms(); st.rerun()
                    
        if not products.empty:
            st.dataframe(products[["Urun_Kodu", "Urun_Adi", "Net_Paket_KG"]])

# --- 2. STOK ---
elif menu == "📦 Hammadde Stok & Limitler":
    st.header("📦 Stok (Bulut)")
    tab1, tab2, tab3 = st.tabs(["Giriş", "Sil", "Limit"])
    inv = load_data("inventory")
    limits = load_data("limits")
    
    with tab1:
        c1, c2, c3 = st.columns(3)
        dt = c1.date_input("Tarih", key=f"sd_{f_key}")
        ing = c2.selectbox("Hammadde", ALL_INGREDIENTS, key=f"si_{f_key}")
        lot = c3.text_input("Parti No", key=f"sl_{f_key}")
        c4, c5 = st.columns(2)
        qty = c4.number_input("KG", key=f"sq_{f_key}")
        amb = 0.0
        if ing in PACKAGING_LIST: amb = c5.number_input("Birim Gr", key=f"sa_{f_key}")
        
        if st.button("Kaydet", key=f"btn_s_{f_key}"):
            sid = f"STK-{datetime.now().strftime('%Y%m%d%H%M%S')}"
            new_row = pd.DataFrame([{"Stok_ID": sid, "Tarih": str(dt), "Hammadde": ing, "Parti_No": lot, "Giris_Miktari": qty, "Kalan_Miktar": qty, "Birim": "KG", "Ambalaj_Birim_Gr": amb}])
            inv = pd.concat([inv, new_row], ignore_index=True)
            save_data(inv, "inventory")
            st.success("Eklendi"); reset_forms(); st.rerun()
        
        if not inv.empty:
            inv["Kalan_Miktar"] = pd.to_numeric(inv["Kalan_Miktar"], errors='coerce')
            st.dataframe(inv[inv["Kalan_Miktar"]>0])

    with tab2:
        if not inv.empty:
            opts = [(i, f"{r['Tarih']} {r['Hammadde']} {r['Parti_No']}") for i,r in inv.sort_values("Tarih", ascending=False).head(20).iterrows()]
            sel = st.selectbox("Seç", opts, format_func=lambda x:x[1], key="del_sel")
            if st.button("Sil"):
                inv = inv.drop(sel[0])
                save_data(inv, "inventory")
                st.success("Silindi"); st.rerun()

    with tab3:
        with st.form("lim_f"):
            upd = []
            cols = st.columns(3)
            for idx, ing in enumerate(ALL_INGREDIENTS):
                curr = limits[limits["Hammadde"]==ing]["Kritik_Limit_KG"].sum()
                val = cols[idx%3].number_input(f"{ing}", value=float(curr))
                upd.append({"Hammadde": ing, "Kritik_Limit_KG": val})
            if st.form_submit_button("Güncelle"):
                save_data(pd.DataFrame(upd), "limits")
                st.success("Güncellendi"); st.rerun()

# --- 3. ÜRETİM ---
elif menu == "📝 Üretim Girişi":
    st.header("📝 Üretim Kaydı")
    prods = load_data("products")
    inv = load_data("inventory")
    if prods.empty: st.warning("Ürün yok"); st.stop()
    
    inv["Kalan_Miktar"] = pd.to_numeric(inv["Kalan_Miktar"], errors='coerce').fillna(0)
    inv["Ambalaj_Birim_Gr"] = pd.to_numeric(inv["Ambalaj_Birim_Gr"], errors='coerce').fillna(0)
    
    c1, c2, c3, c4 = st.columns(4)
    p_date = c1.date_input("Tarih", datetime.today(), key=f"pd_{f_key}")
    p_sel = c2.selectbox("Ürün", prods["Urun_Kodu"].unique(), key=f"ps_{f_key}")
    curr = prods[prods["Urun_Kodu"] == p_sel].iloc[0]
    p_lot = c3.text_input("Parti No", key=f"pl_{f_key}")
    p_pack = c4.number_input("Paket Sayısı", value=0, key=f"pk_{f_key}")
    
    net_kg = p_pack * float(curr["Net_Paket_KG"])
    if p_pack > 0: st.info(f"Hedef: {net_kg} KG")
    
    rec_solid = ast.literal_eval(curr["Recete_Kati_JSON"])
    rec_liquid = ast.literal_eval(curr.get("Recete_Sivi_JSON", "{}"))
    inputs = {}
    
    total_fire_amb = 0.0
    st.subheader("1. Ambalaj")
    for pt in PACKAGING_LIST:
        stock = inv[(inv["Hammadde"]==pt) & (inv["Kalan_Miktar"]>0)]
        c_a, c_b = st.columns(2)
        opts = stock.to_dict('records')
        disp = [None] + opts
        sel = c_a.selectbox(f"{pt} Parti", disp, format_func=lambda x: "Seçiniz..." if x is None else f"{x['Parti_No']} ({x['Kalan_Miktar']})", key=f"ps_{pt}_{f_key}")
        act = c_b.number_input(f"{pt} Adet", value=0, key=f"pa_{pt}_{f_key}")
        
        if sel and act>0:
            ukg = sel['Ambalaj_Birim_Gr']/1000
            ckg = act*ukg
            inputs[pt] = [{"qty": ckg, "lot": sel['Parti_No']}]
            if p_pack>0: total_fire_amb += (act-p_pack)*ukg
        else: inputs[pt] = None
        
    st.divider(); st.subheader("2. Katı")
    act_s, theo_s = 0.0, 0.0
    for ing in SOLID_INGREDIENTS:
        rat = rec_solid.get(ing, 0.0)
        if rat>0:
            theo = net_kg*rat; theo_s += theo
            st.write(f"{ing} (Teorik: {theo:.2f})")
            c1, c2, c3, c4 = st.columns([1.5,2,1.5,2])
            a1 = c1.number_input("Miktar 1", key=f"a1_{ing}_{f_key}")
            opts = inv[(inv["Hammadde"]==ing) & (inv["Kalan_Miktar"]>0)]
            lots = [str(r['Parti_No'])+f" ({r['Kalan_Miktar']})" for _,r in opts.iterrows()]
            l1 = c2.selectbox("Parti 1", ["Seçiniz..."]+lots, key=f"l1_{ing}_{f_key}")
            a2 = c3.number_input("Ek", key=f"a2_{ing}_{f_key}")
            l2 = c4.selectbox("Ek Parti", ["Seçiniz..."]+lots, key=f"l2_{ing}_{f_key}")
            act_s += (a1+a2)
            ent = []
            if a1>0: ent.append({"qty": a1, "lot": l1})
            if a2>0: ent.append({"qty": a2, "lot": l2})
            inputs[ing] = ent
            st.markdown("---")
            
    st.divider(); st.subheader("3. Sıvı")
    act_l, theo_l = 0.0, 0.0
    for ing in LIQUID_INGREDIENTS:
        req = rec_liquid.get(ing, 0.0)
        theo = (net_kg/100)*req; theo_l += theo
        st.write(f"{ing} (Teorik: {theo:.2f})")
        c1, c2 = st.columns(2)
        a1 = c1.number_input("Fiili", key=f"fa_{ing}_{f_key}")
        opts = inv[(inv["Hammadde"]==ing) & (inv["Kalan_Miktar"]>0)]
        lots = [str(r['Parti_No'])+f" ({r['Kalan_Miktar']})" for _,r in opts.iterrows()]
        l1 = c2.selectbox("Parti", ["Seçiniz..."]+lots, key=f"fl_{ing}_{f_key}")
        act_l += a1
        if a1>0: inputs[ing] = [{"qty": a1, "lot": l1}]
        else: inputs[ing] = []

    if st.button("Kaydet", type="primary", key=f"sv_{f_key}"):
        if p_pack<=0: st.error("Paket sayısı girin!"); st.stop()
        err=False
        for k,v in inputs.items():
            if v:
                for e in v:
                    if e['qty']>0 and "Seçiniz..." in e['lot']: st.error(f"{k} parti seçilmedi!"); err=True
        if not err:
            uid = f"URT-{datetime.now().strftime('%Y%m%d%H%M%S')}"
            skt = p_date + timedelta(days=int(curr["Raf_Omru_Ay"]*30))
            
            log = {
                "Uretim_ID": uid, "Tarih": str(p_date), "Urun_Kodu": p_sel, "Uretim_Parti_No": p_lot,
                "Uretilen_Paket": p_pack, "Uretilen_Net_KG": net_kg,
                "Fire_Kati_KG": act_s - theo_s, "Fire_Sivi_KG": act_l - theo_l, "Fire_Amb_KG": total_fire_amb
            }
            
            prod = load_data("production")
            inv = load_data("inventory")
            
            for ing, entries in inputs.items():
                if entries:
                    for i, e in enumerate(entries):
                        cln = e['lot'].split(" (")[0]
                        log[f"Kullanim_{ing}_{i+1}"] = e['qty']
                        log[f"Parti_{ing}_{i+1}"] = cln
                        msk = (inv["Hammadde"]==ing) & (inv["Parti_No"].astype(str)==cln)
                        if msk.any():
                            idx = inv[msk].index[0]
                            inv.at[idx, "Kalan_Miktar"] = float(inv.at[idx, "Kalan_Miktar"]) - float(e['qty'])
            
            prod = pd.concat([prod, pd.DataFrame([log])], ignore_index=True)
            fg = load_data("finished_goods")
            nfg = pd.DataFrame([{
                "Uretim_ID": uid, "Urun_Kodu": p_sel, "Uretim_Parti_No": p_lot, 
                "Uretim_Tarihi": str(p_date), "SKT": str(skt), "Baslangic_Net_KG": net_kg, 
                "Kalan_Net_KG": net_kg, "Paket_Agirligi": float(curr["Net_Paket_KG"])
            }])
            fg = pd.concat([fg, nfg], ignore_index=True)
            
            save_data(prod, "production")
            save_data(inv, "inventory")
            save_data(fg, "finished_goods")
            st.success("Kaydedildi!"); reset_forms(); st.rerun()

# --- 4. SEVKİYAT ---
elif menu == "🚚 Sevkiyat & Son Ürün":
    st.header("🚚 Sevkiyat")
    tab1, tab2 = st.tabs(["Sevkiyat Yap", "Geçmiş"])
    fg = load_data("finished_goods")
    sh = load_data("shipments")
    
    if not fg.empty: fg["Kalan_Net_KG"] = pd.to_numeric(fg["Kalan_Net_KG"], errors='coerce').fillna(0)

    with tab1:
        if not fg.empty:
            act = fg[fg["Kalan_Net_KG"]>0].copy()
            if not act.empty:
                sel_p = st.selectbox("Ürün", act["Urun_Kodu"].unique(), key=f"shp_p_{f_key}")
                opts = act[act["Urun_Kodu"]==sel_p]
                lst = [(i, f"{r['Uretim_Parti_No']} ({r['Kalan_Net_KG']}kg)") for i,r in opts.iterrows()]
                sel_i = st.selectbox("Parti", lst, format_func=lambda x:x[1], key=f"shp_l_{f_key}")[0]
                sel_r = fg.loc[sel_i]
                
                c1,c2,c3 = st.columns(3)
                cus = c1.text_input("Müşteri", key=f"sc_{f_key}")
                typ = c2.selectbox("Tip", ["Satış", "Numune"], key=f"st_{f_key}")
                kg = c3.number_input(f"KG (Max {sel_r['Kalan_Net_KG']})", max_value=float(sel_r['Kalan_Net_KG']), key=f"sk_{f_key}")
                
                if st.button("Sevk Et", key=f"btn_s_{f_key}"):
                    fg.at[sel_i, "Kalan_Net_KG"] -= kg
                    ns = pd.DataFrame([{
                        "Sevkiyat_ID": f"S-{datetime.now().strftime('%Y%m%d%H%M')}",
                        "Tarih": str(datetime.now()), "Uretim_ID": sel_r["Uretim_ID"],
                        "Musteri": cus, "Tip": typ, "Sevk_Edilen_KG": kg, "Aciklama": ""
                    }])
                    sh = pd.concat([sh, ns], ignore_index=True)
                    save_data(sh, "shipments"); save_data(fg, "finished_goods")
                    st.success("Kaydedildi"); reset_forms(); st.rerun()
            else: st.info("Stok Yok")

    with tab2:
        if not sh.empty: st.dataframe(sh)

# --- 5. İZLENEBİLİRLİK ---
elif menu == "🔍 İzlenebilirlik":
    st.header("🔍 İzlenebilirlik")
    prod = load_data("production")
    if not prod.empty:
        prod["Tarih_Fmt"] = prod["Tarih"].apply(format_date_tr)
        prod["Etiket"] = prod["Uretim_Parti_No"] + " (" + prod["Tarih_Fmt"] + ")"
        sel = st.selectbox("Üretim Seç", prod["Etiket"].unique())
        row = prod[prod["Etiket"]==sel].iloc[0]
        st.write("### Detaylar")
        st.json(row.to_dict())

# --- 6. RAPORLAR ---
elif menu == "📊 Raporlar":
    st.header("📊 Raporlar")
    prod = load_data("production")
    if not prod.empty:
        def safe_div(n, d): return n/d*100 if d > 0 else 0
        prod["Giren Katı"] = prod["Uretilen_Net_KG"] + prod["Fire_Kati_KG"]
        prod["Katı Fire %"] = prod.apply(lambda x: safe_div(x["Fire_Kati_KG"], x["Giren Katı"]), axis=1)
        prod["Sıvı Fire %"] = prod.apply(lambda x: safe_div(x["Fire_Sivi_KG"], x["Uretilen_Net_KG"]), axis=1)
        prod["Ambalaj Fire (Gr/Paket)"] = prod.apply(lambda x: safe_div(x["Fire_Amb_KG"]*1000, x["Uretilen_Paket"])/100, axis=1)
        
        cols = ["Tarih", "Urun_Kodu", "Uretim_Parti_No", "Uretilen_Net_KG", "Fire_Kati_KG", "Katı Fire %", "Sıvı Fire %", "Ambalaj Fire (Gr/Paket)"]
        exist = [c for c in cols if c in prod.columns]
        prod["Tarih"] = prod["Tarih"].apply(format_date_tr)
        st.dataframe(prod[exist].style.format({"Katı Fire %": "{:.2f}%", "Sıvı Fire %": "{:.2f}%", "Ambalaj Fire (Gr/Paket)": "{:.1f} gr"}))