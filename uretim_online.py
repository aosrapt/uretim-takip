import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, timedelta
import ast

# --- AYARLAR ---
st.set_page_config(page_title="Online Üretim (Admin)", layout="wide", page_icon="🔒")

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

def get_worksheet(tab_name):
    client = get_gsheet_client()
    if not client: return None
    try:
        sh = client.open(SHEET_NAME)
        try: ws = sh.worksheet(tab_name)
        except: ws = sh.add_worksheet(title=tab_name, rows="100", cols="20")
        return ws
    except: return None

# --- VERİ YÖNETİMİ ---
TABS = {
    "production": "uretim_loglari", "inventory": "stok_durumu",
    "products": "urun_tanimlari", "finished_goods": "bitmis_urunler",
    "shipments": "sevkiyatlar", "limits": "limitler", "ingredients": "bilesenler"
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
        data = [df.columns.values.tolist()] + df.astype(str).values.tolist()
        ws.update(data)

# --- FORMATLAR & RESET ---
if 'form_key' not in st.session_state: st.session_state['form_key'] = 0
if 'is_admin' not in st.session_state: st.session_state['is_admin'] = False

def reset_forms(): st.session_state['form_key'] += 1

def format_date_tr(date_obj):
    if pd.isna(date_obj) or str(date_obj)=="": return "-"
    try: return pd.to_datetime(date_obj).strftime("%d/%m/%Y")
    except: return str(date_obj)

# --- GLOBAL LİSTELER ---
df_ing_global = load_data("ingredients")
if not df_ing_global.empty:
    SOLID = df_ing_global[df_ing_global["Tip"] == "Katı"]["Bilesen_Adi"].tolist()
    LIQUID = df_ing_global[df_ing_global["Tip"] == "Sıvı"]["Bilesen_Adi"].tolist()
    PACKAGING = df_ing_global[df_ing_global["Tip"] == "Ambalaj"]["Bilesen_Adi"].tolist()
    ALL_ING = SOLID + LIQUID + PACKAGING
else: SOLID, LIQUID, PACKAGING, ALL_ING = [],[],[],[]

# --- LOGIN & SIDEBAR ---
st.sidebar.title("🏭 Fabrika Paneli")

# GİRİŞ KONTROLÜ
with st.sidebar:
    if not st.session_state['is_admin']:
        st.info("👀 Misafir Modu (Sadece İzleme)")
        pwd = st.text_input("Yönetici Şifresi", type="password")
        if st.button("Giriş Yap"):
            if pwd == st.secrets["admin_password"]:
                st.session_state['is_admin'] = True
                st.success("Giriş Başarılı!")
                st.rerun()
            else:
                st.error("Hatalı Şifre!")
    else:
        st.success("🔓 Yönetici Modu Aktif")
        if st.button("Çıkış Yap"):
            st.session_state['is_admin'] = False
            st.rerun()
    
    st.divider()

# MENÜ AYARLAMASI (Yetkiye Göre)
if st.session_state['is_admin']:
    # Admin Menüsü (Tam Erişim)
    menu_options = [
        "📝 Üretim Girişi", 
        "📦 Stok & Limitler", 
        "⚙️ Reçete & Hammadde",
        "🚚 Sevkiyat & Son Ürün", 
        "🔍 İzlenebilirlik",
        "📊 Raporlar"
    ]
else:
    # Misafir Menüsü (Sadece Okuma)
    menu_options = [
        "🔍 İzlenebilirlik",
        "📊 Raporlar",
        "📦 Stok Durumu (İzle)",
        "🚚 Son Ürün (İzle)"
    ]

menu = st.sidebar.radio("Menü Seçimi", menu_options)
f_key = st.session_state['form_key']

# -------------------------------------------------------------------
# SAYFA İÇERİKLERİ
# -------------------------------------------------------------------

# --- ADMIN SAYFALARI ---

if menu == "⚙️ Reçete & Hammadde":
    st.header("⚙️ Reçete & Hammadde Yönetimi")
    tab1, tab2 = st.tabs(["Ürün/Reçete", "Hammadde Ekle"])
    
    with tab2:
        c1,c2 = st.columns(2)
        nn = c1.text_input("Ad", key=f"in_{f_key}"); nt = c2.selectbox("Tip", ["Katı","Sıvı","Ambalaj"], key=f"it_{f_key}")
        if st.button("Ekle", key=f"bi_{f_key}"):
            if nn and nn not in ALL_ING:
                df = load_data("ingredients")
                df = pd.concat([df, pd.DataFrame([[nn, nt]], columns=["Bilesen_Adi","Tip"])], ignore_index=True)
                save_data(df, "ingredients")
                dfl = load_data("limits")
                dfl = pd.concat([dfl, pd.DataFrame([[nn, 0]], columns=["Hammadde","Kritik_Limit_KG"])], ignore_index=True)
                save_data(dfl, "limits")
                st.success("Eklendi"); reset_forms(); st.rerun()
        st.dataframe(df_ing_global)

    with tab1:
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
            st.dataframe(dv[["Urun_Kodu","Urun_Adi","Net_Paket_KG","Katı","Sıvı"]])

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
                cur = lim[lim["Hammadde"]==ig]["Kritik_Limit_KG"].sum()
                v = st.number_input(f"{ig}", float(cur))
                upd.append({"Hammadde":ig, "Kritik_Limit_KG":v})
            if st.form_submit_button("Güncelle"): save_data(pd.DataFrame(upd), "limits"); st.success("OK"); st.rerun()

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
    inp={}; tf_amb=0.0
    
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
            if a1>0: en.append({"qty":a1, "lot":l1})
            if a2>0: en.append({"qty":a2, "lot":l2})
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
        if a1>0: inp[lg]=[{"qty":a1, "lot":l1}]
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
            log={"Uretim_ID":uid, "Tarih":str(pdts), "Urun_Kodu":psel, "Uretim_Parti_No":plot, "Uretilen_Paket":ppck, "Uretilen_Net_KG":nkg, "Fire_Kati_KG":acts-theos, "Fire_Sivi_KG":actl-theol, "Fire_Amb_KG":tf_amb}
            
            prod=load_data("production")
            for k,v in inp.items():
                if v:
                    for i,e in enumerate(v):
                        cn=e['lot'].split(" (")[0]
                        log[f"Kullanim_{k}_{i+1}"]=e['qty']; log[f"Parti_{k}_{i+1}"]=cn
                        msk=(inv["Hammadde"]==k)&(inv["Parti_No"].astype(str)==cn)
                        if msk.any(): idx=inv[msk].index[0]; inv.at[idx,"Kalan_Miktar"]=float(inv.at[idx,"Kalan_Miktar"])-float(e['qty'])
            
            prod=pd.concat([prod, pd.DataFrame([log])], ignore_index=True)
            fg=load_data("finished_goods")
            nfg=pd.DataFrame([{"Uretim_ID":uid, "Urun_Kodu":psel, "Uretim_Parti_No":plot, "Uretim_Tarihi":str(pdts), "SKT":str(skt), "Baslangic_Net_KG":nkg, "Kalan_Net_KG":nkg, "Paket_Agirligi":float(curr["Net_Paket_KG"])}])
            fg=pd.concat([fg, nfg], ignore_index=True)
            
            save_data(prod, "production"); save_data(inv, "inventory"); save_data(fg, "finished_goods")
            st.success("Kaydedildi"); reset_forms(); st.rerun()

elif menu == "🚚 Sevkiyat & Son Ürün":
    st.header("🚚 Sevkiyat")
    t1,t2,t3 = st.tabs(["Sevk Et", "Geçmiş", "Stok"])
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
                ty=c2.selectbox("Tip", ["Satış","Numune"], key=f"sty_{f_key}")
                kg=c3.number_input(f"KG (Max {sr['Kalan_Net_KG']})", max_value=float(sr['Kalan_Net_KG']), key=f"skg_{f_key}")
                nt=st.text_input("Not", key=f"snt_{f_key}")
                if st.button("Sevk Et", key=f"sbt_{f_key}"):
                    fg.at[si, "Kalan_Net_KG"]-=kg
                    ns=pd.DataFrame([{"Sevkiyat_ID":f"S-{datetime.now().strftime('%Y%m%d%H%M')}", "Tarih":str(datetime.now()), "Uretim_ID":sr["Uretim_ID"], "Musteri":cu, "Tip":ty, "Sevk_Edilen_KG":kg, "Aciklama":nt}])
                    sh=pd.concat([sh, ns], ignore_index=True)
                    save_data(sh, "shipments"); save_data(fg, "finished_goods")
                    st.success("Kaydedildi"); reset_forms(); st.rerun()
            else: st.info("Stok yok")
    with t2:
        if not sh.empty: 
            sh["Tarih"]=sh["Tarih"].apply(format_date_tr)
            st.dataframe(sh.sort_values("Sevkiyat_ID", False))
    with t3:
        if not fg.empty:
            v=fg[fg["Kalan_Net_KG"]>0].copy()
            v["Tarih"]=v["Uretim_Tarihi"].apply(format_date_tr); v["SKT"]=v["SKT"].apply(format_date_tr)
            v["Paket"]=v["Kalan_Net_KG"]/v["Paket_Agirligi"]
            st.dataframe(v[["Urun_Kodu","Uretim_Parti_No","Tarih","SKT","Kalan_Net_KG","Paket"]])

# --- MİSAFİR/ADMIN ORTAK GÖRÜNEN SAYFALAR ---

elif menu == "🔍 İzlenebilirlik":
    st.header("🔍 İzlenebilirlik")
    prod=load_data("production"); fg=load_data("finished_goods")
    if not prod.empty:
        prod["Tarih_Fmt"]=prod["Tarih"].apply(format_date_tr)
        prod["Etiket"]=prod["Uretim_Parti_No"]+" ("+prod["Tarih_Fmt"]+")"
        sel=st.selectbox("Seç", prod["Etiket"].unique())
        row=prod[prod["Etiket"]==sel].iloc[0]
        uid=row["Uretim_ID"]
        rel=fg[fg["Uretim_ID"]==uid]
        
        c1,c2,c3,c4=st.columns(4)
        c1.metric("Tarih", format_date_tr(row["Tarih"]))
        c2.metric("Depoda", f"{(datetime.now()-pd.to_datetime(row['Tarih'])).days} Gün")
        if not rel.empty:
            c3.metric("SKT", format_date_tr(rel.iloc[0]["SKT"]))
            c4.metric("Stok", f"{rel.iloc[0]['Kalan_Net_KG']:.2f} KG")
        else: c3.metric("Durum", "Silindi")
        
        st.write("Hammadde:"); u=[]
        for ig in ALL_ING:
            for i in range(1,3):
                if row.get(f"Kullanim_{ig}_{i}",0)>0: u.append({"Hammadde":ig, "Parti":row.get(f"Parti_{ig}_{i}"), "Miktar":row[f"Kullanim_{ig}_{i}"]})
        st.table(pd.DataFrame(u))

elif menu == "📊 Raporlar":
    st.header("📊 Raporlar")
    prod=load_data("production")
    if not prod.empty:
        def sd(n,d): return n/d*100 if d>0 else 0
        prod["Giren"]=prod["Uretilen_Net_KG"]+prod["Fire_Kati_KG"]
        prod["Katı %"]=prod.apply(lambda x:sd(x["Fire_Kati_KG"],x["Giren"]), axis=1)
        prod["Sıvı %"]=prod.apply(lambda x:sd(x["Fire_Sivi_KG"],x["Uretilen_Net_KG"]), axis=1)
        prod["Amb (gr/pkt)"]=prod.apply(lambda x:sd(x["Fire_Amb_KG"]*1000,x["Uretilen_Paket"])/100, axis=1)
        
        cols=["Tarih","Urun_Kodu","Uretim_Parti_No","Uretilen_Net_KG","Fire_Kati_KG","Katı %","Sıvı %","Amb (gr/pkt)"]
        fin=[c for c in cols if c in prod.columns]
        prod["Tarih"]=prod["Tarih"].apply(format_date_tr)
        st.dataframe(prod[fin].style.format({"Katı %":"{:.2f}%","Sıvı %":"{:.2f}%","Fire_Kati_KG":"{:.2f}","Amb (gr/pkt)":"{:.1f} gr"}))

# Misafir Menüsü Özel Sayfalar (Admin zaten görüyor)
elif menu == "📦 Stok Durumu (İzle)":
    st.header("📦 Stok Durumu")
    inv = load_data("inventory")
    if not inv.empty:
        inv["Kalan_Miktar"] = pd.to_numeric(inv["Kalan_Miktar"], errors='coerce')
        st.dataframe(inv[inv["Kalan_Miktar"] > 0][["Tarih", "Hammadde", "Parti_No", "Kalan_Miktar"]])

elif menu == "🚚 Son Ürün (İzle)":
    st.header("🚚 Son Ürün Stokları")
    fg = load_data("finished_goods")
    if not fg.empty:
        fg["Kalan_Net_KG"] = pd.to_numeric(fg["Kalan_Net_KG"], errors='coerce')
        v = fg[fg["Kalan_Net_KG"] > 0].copy()
        v["Tarih"] = v["Uretim_Tarihi"].apply(format_date_tr)
        v["SKT"] = v["SKT"].apply(format_date_tr)
        st.dataframe(v[["Urun_Kodu", "Uretim_Parti_No", "Tarih", "SKT", "Kalan_Net_KG"]])
