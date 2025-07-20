# main.py
import uuid
import pathlib, sys
from sqlalchemy.orm import joinedload
from threading import Timer
from datetime import datetime, timedelta
from fastapi import FastAPI, Request, HTTPException, Body, status, Depends,Query
from fastapi import BackgroundTasks,Form
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.responses import RedirectResponse
import asyncio
from starlette.middleware.sessions import SessionMiddleware

# importe la config et les modèles
from app.utils import engine, SessionLocal, Base, Session as SessionModel, Credit, Pricing,Station,ValidatedPayment
from app.seed import*

token = 'b03e89d2f3b44516a9b587a21b9e7bcd83eb697e46c0b242d37a453be1611229'
# … configuration FastAPI …
app = FastAPI(title="PlayHub 32 – API v2")
app.add_middleware(SessionMiddleware, secret_key=token)  # choisis une vraie clé en prod
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")


#from escpos.printer import Network


def print_gamer_receipt(session, station):
    p = Network("192.168.1.123")  # Ton IP de l’imprimante

    # LOGO ASCII (tu peux charger une image binaire aussi)
    p.set(align='center', width=2, height=2, bold=True)
    p.text("┏━━━━━━━━━━━━━━━━━━━━┓\n")
    p.text("★ PLAYHUB 32 ARENA ★\n")
    p.text("┗━━━━━━━━━━━━━━━━━━━━┛\n")
    p.set(align='center', width=1, height=1, bold=False)
    p.text("Le QG du gamer\n")
    p.text("--------------------------------\n")

    # Infos principales
    p.set(align='center', bold=True, width=2, height=1)
    p.text("SESSION DE JEU\n")
    p.set(align='left', bold=False, width=1, height=1)
    p.text("--------------------------------\n")
    p.set(bold=True)
    p.text(f"Session : {session.ref_code}\n")
    p.text(f"Poste   : {station.name}\n")
    p.text(f"Durée   : {session.minutes_total} min\n")
    p.text(f"Montant : {session.amount} F\n")
    p.set(bold=False)
    p.text(f"Début   : {session.start_at.strftime('%d/%m/%Y %H:%M')}\n")
    p.text(f"Fin     : {session.end_at.strftime('%d/%m/%Y %H:%M')}\n")
    p.text("--------------------------------\n")

    # QR code pour valider, ou “feedback” ou promo
    p.set(align='center')
    p.text("Scanne pour info ou support :\n")
    p.qr(f"https://playhub32.cm/ticket/{session.ref_code}", size=6)
    p.text("\n")

    # Footer style "Arcade"
    p.set(align='center', bold=True)
    p.text("Bonne partie ! 🎮\n")
    p.text("Merci de votre visite\n")
    p.set(align='center', width=2, height=2)
    p.text("PLAYHUB32 ARENA\n")
    p.cut()


# Dépendance pour la session DB
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Graines initiales
print_seed_info()  # pricing and stations

# Administrateurs
ADMINS = {
    "admin": "sim",
    "simplice": "din"
}
# Jeux disponibles
GAMES = [
    {"id":1, "name":"EA Sports FC 25","img":"/static/jeux/EA-Sports-FC-25.jpg"},
    {"id":2, "name":"UFL","img":"/static/jeux/UFL.png"},
    {"id":3, "name":"Warzon II","img":"/static/jeux/warzon.jpg"},
    {"id":4, "name":"NBA 2K 25","img":"/static/jeux/NBA-2K25.png"},
    {"id":5, "name":"Gran Turismo 7","img":"/static/jeux/gran-turismo-7.png"},
    {"id":6, "name":"Fortnite","img":"/static/jeux/fortnite.png"},
    {"id":7, "name":"Tekken 8","img":"/static/jeux/tekken-8.png"},
    {"id":8, "name":"Spider-Man 2","img":"/static/jeux/spider-men.png"},
    {"id":9, "name":"Mortal Kombat 1","img":"/static/jeux/mortal-kombat-1.png"},
    {"id":10,"name":"Overcooked! All You Can Eat","img":"/static/jeux/overcooked-all-eat.png"}
]

# Create tables
Base.metadata.create_all(bind=engine)
print_seed_info() # pricing and stations


# Scheduler functions
def render_error(request: Request, code: int, msg: str):
    print(f"[Error] {code} - {msg}")
    return templates.TemplateResponse(
        "session_error.html",
        {"request": request, "error_code": code, "error_message": msg},
        status_code = code
    )
#
async def session_watcher():
    while True:
        print("[Watcher] 🔍 Vérification des sessions...")
        db = SessionLocal()
        try:
            now = datetime.utcnow()

            ### 1. Sessions PAYÉES (en cours d’utilisation)
            active_sessions = db.query(SessionModel).filter(
                SessionModel.status == "PAID"
            ).all()

            for sess in active_sessions:
                raw_elapsed = (now - sess.last_active).total_seconds()
                elapsed = 0
                if raw_elapsed > 90:
                    # ⚠️ Coupure détectée → on relance la session sans déduire le temps
                    print(f"[Watcher] ⚠️ Coupure détectée sur session {sess.ref_code} (inactivité {int(raw_elapsed)}s)")
                    
                    # Repositionner le point de reprise
                    sess.last_active = now

                    # Recalcul de la nouvelle heure de fin (pour affichage)
                    remaining = max(sess.minutes_total - sess.minutes_used, 0)
                    sess.end_at = now + timedelta(minutes=remaining)

                    db.add(sess)
                    continue  # On saute l’incrémentation du temps
                else:
                    elapsed = int(raw_elapsed / 60)

                if elapsed > 0:
                    sess.minutes_used += elapsed
                    sess.last_active = now
                    sess.minutes_left = max(sess.minutes_total - sess.minutes_used, 0)
                    remaining = max(sess.minutes_total - sess.minutes_used, 0)
                    sess.end_at = now + timedelta(minutes=remaining)

                    print(f"[Watcher] ⏳ Session {sess.ref_code} +{elapsed} min (used {sess.minutes_used}/{sess.minutes_total})")

                    if sess.minutes_used >= sess.minutes_total:
                        sess.status = "FINISHED"
                        station = db.query(Station).get(sess.station_id)
                        if station:
                            station.status = "FREE"
                            db.add(station)
                        print(f"[Watcher] ✅ Session {sess.ref_code} terminée")

                    db.add(sess)

            ### 2. Sessions DRAFT (PENDING) non payées dans les 2 min
            draft_expiry = now - timedelta(minutes=2)
            expired_drafts = db.query(SessionModel).filter(
                SessionModel.status == "PENDING",
                SessionModel.start_at <= draft_expiry
            ).all()

            for sess in expired_drafts:
                sess.status = "EXPIRED"
                station = db.query(Station).get(sess.station_id)
                if station:
                    station.status = "FREE"
                    db.add(station)
                print(f"[Watcher] ❌ Draft expiré : {sess.ref_code}")
                db.add(sess)

            db.commit()

        finally:
            db.close()

        await asyncio.sleep(30)  # Relance la vérification toutes les 30 secondes


def admin_required(request: Request):
    if not request.session.get("admin_logged_in"):
        # Redirige vers login ou renvoie une erreur 403 si tu veux une API REST pure
        return RedirectResponse("/admin", status_code=302)


# 1. Accueil
@app.get("/", response_class=HTMLResponse)
async def kiosk(request: Request):
    return templates.TemplateResponse("kiosk_welcome.html", {"request": request})

# 2. Tarifs et stations
@app.get("/pricing")
def get_pricing(db=Depends(get_db)):
    return [
        {"id": p.id, "label": p.label, "minutes": p.minutes, "price": p.price, "is_decoy": p.is_decoy}
        for p in db.query(Pricing).all()
    ]

@app.get("/stations")
def get_stations(db=Depends(get_db)):
    return [
        {"id": s.id, "name": s.name, "location": s.location, "status": s.status}
        for s in db.query(Station).all()
    ]

# 3. Draft session
@app.post("/session/draft", status_code=201)
def draft_session(request: Request,
    payload: dict = Body(...),
    db=Depends(get_db)
):
    offer = db.query(Pricing).filter(Pricing.id == payload.get("offer_id")).first()
    if not offer:
        return render_error(request,400,"Unknown offer")
    
    station = db.query(Station).get(payload.get("station_id"))
    
    if not station or station.status != "FREE":
        return render_error(request,409,"Station not available")


    id = payload.get("txn_id")
    Pay = db.query(ValidatedPayment).filter(ValidatedPayment.txn_id == id).first()
    if not Pay:
        return render_error(request,504, "Payment not found")
    if Pay.is_used and Pay.amount < offer.price:
        return render_error(request,503, "Payment already used or insufficient amount")
    if Pay.amount < offer.price:
        return render_error(request,505, "Insufficient payment amount")
    # Marquer le paiement comme utilisé
    #print(f"[Draft] Paiement {Pay.txn_id} validé pour l’offre {offer.label} ({offer.minutes} min)")
    #Pay.is_used = True
    #Pay.amount -= offer.price
    
    ref_code = uuid.uuid4().hex[:8]
    now = datetime.utcnow()
    new_sess = SessionModel(
        station_id    = station.id,
        offer_id      = offer.id,
        minutes_total = offer.minutes,
        minutes_left  = offer.minutes,
        phone         = Pay.client_phone,
        amount        = offer.price,
        txn_id        = Pay.txn_id,
        ref_code      = ref_code,
        offer         = offer,
        status        = "PENDING",
        start_at      = now,
        end_at        = now + timedelta(minutes=offer.minutes)
    )
    db.add(Pay)
    db.add(new_sess)
    station.status = "PENDING"
    db.add(station)
    db.commit()
    db.refresh(new_sess)

    # Planifier expiration auto
    #background_tasks.add_task(schedule_expiration, new_sess.ref_code, 120)
    #print(f"[Draft] Nouvelle session {new_sess.ref_code} créée pour {offer.label} ({offer.minutes} min)")
    return {"session_id": new_sess.ref_code}

# 4.  Page de confirmation
@app.get("/payment/{session_id}", response_class=HTMLResponse)
def show_summary(
    session_id: str,
    request: Request,
    db = Depends(get_db)
):
    # ⇢ Session + relations ----------------------------------------------------
    sess = (
        db.query(SessionModel)
          .filter(SessionModel.ref_code == session_id)
          .first()
    )
    if not sess:
        raise HTTPException(404, "Session introuvable")

    offer   = db.get(Pricing,  sess.offer_id)
    station = db.get(Station,  sess.station_id)

    # ⇢ Paiement déjà validé ---------------------------------------------------
    payment = (
        db.query(ValidatedPayment)
          .filter(ValidatedPayment.client_phone == sess.phone)  # ← cf. champ que tu as ajouté à SessionModel
          .first()
    )

    return templates.TemplateResponse(
        "session_review.html",
        {
            "request":  request,
            "session":  sess,
            "offer":    offer,
            "station":  station,
            "payment":  payment,
        }
    )

@app.post("/session/confirm/{ref_code}")
def confirm_session(ref_code: str, db=Depends(get_db)):
    sess = db.query(SessionModel).filter(SessionModel.ref_code == ref_code).first()
    station = db.query(Station).get(sess.station_id)
    Pay = db.query(ValidatedPayment).filter(
        ValidatedPayment.txn_id == sess.txn_id
    ).first()
    if not sess:
        raise HTTPException(404, "Session introuvable")
    if sess.status == "EXPIRED":
        raise HTTPException(400, "Session expirée, veuillez en créer une nouvelle")
    if not station or station.status != "PENDING":
        raise HTTPException(409, "Station non disponible")
    if not Pay or Pay.amount < sess.amount:
        raise HTTPException(503, "Paiement non valide ou insuffisant")
    # Marquer le paiement comme utilisé
    Pay.is_used = True
    Pay.amount -= sess.amount
    db.add(Pay)
    # ... logique de validation paiement/session ici ...
    # exemple :
    sess.status = "PAID"
    station.status = "BUSY"
    db.add(station)
    db.add(sess)
    db.commit()
    #print_gamer_receipt(sess, station)
    return {"ok": True}


# 7. Jeux
@app.get("/games", response_class=HTMLResponse)
def games_page(request: Request):
    return templates.TemplateResponse("game.html", {"request": request, "games": GAMES})

@app.get("/games-data")
def games_data():
    return JSONResponse(content=GAMES)


@app.get("/extend", response_class=HTMLResponse)
def extend_page(request: Request):
    return templates.TemplateResponse("extend.html", {"request": request})


@app.post("/session/extend/preview")
def preview_extend(ref_code: str = Form(...), extension: int = Form(...), txn_id: str = Form(...), db=Depends(get_db)):
    sess = db.query(SessionModel).filter_by(ref_code=ref_code).first()
    if not sess:
        raise HTTPException(404)
    prices = {15: 1000, 60: 2000, 120: 3500}
    amount = prices.get(extension, 0)
    return {
      "extension": extension,
      "amount": amount,
      "txn_id": txn_id,
      "old_end": sess.end_at.isoformat(),
      "new_end": (sess.end_at + timedelta(minutes=extension)).isoformat()
    }


@app.post("/session/extend/validate")
def extend_validate(
    ref_code: str = Form(..., min_length=8, max_length=8),
    extension: int = Form(...),
    txn_id: str = Form(..., min_length=20, max_length=20),
    db=Depends(get_db)
):
    sess = db.query(SessionModel).filter(SessionModel.ref_code == ref_code).first()
    if not sess or sess.status not in ["PAID"]:
        raise HTTPException(400, "Référence invalide ou session non payable")

    prices = {15: 1000, 60: 2000, 120: 3500}
    if extension not in prices:
        raise HTTPException(400, "Durée invalide")
    amount = prices[extension]

    pay = db.query(ValidatedPayment).filter(
        ValidatedPayment.txn_id == txn_id
    ).first()
    station = db.query(Station).get(sess.station_id)
    if not pay:
        raise HTTPException(400, "Paiement non trouvé")
    if pay.amount < amount:
        raise HTTPException(400, "Montant du paiement insuffisant")

    # On retire le montant, et prolonge la session
    pay.amount -= amount
    sess.minutes_total += extension
    sess.amount = (sess.amount or 0) + amount
    sess.minutes_left = int(sess.minutes_left + extension)
    sess.end_at += timedelta(minutes=extension)
    sess.status = "PAID"

    db.add(pay)
    db.add(sess)
    db.commit()
    db.refresh(sess)
    # print_gamer_receipt(sess, station)
    return {"ok": True, "new_end": sess.end_at.isoformat(), "minutes_left": sess.minutes_left}

# 10. Page Relancer / Sauvegarder
@app.get("/session/manage", response_class=HTMLResponse)
def manage_session_page(request: Request, ref_code: str = None, db=Depends(get_db)):
    """
    Affiche la page de gestion de session :
    - si ref_code fourni, charge la session et affiche temps restant
    - sinon, champ vide pour saisie
    """
    session = None
    if ref_code:
        session = db.query(SessionModel).filter(SessionModel.ref_code == ref_code).first()
        if not session:
            raise HTTPException(404, "Session introuvable")
    return templates.TemplateResponse(
        "relance_sauvegarde.html",
        {"request": request, "session": session}
    )

# 11. Sauvegarder (mettre en pause) une session 
@app.post("/session/save")
def save_session(
    request: Request,  # <= N'oublie pas de le rajouter ici !
    ref_code: str = Form(..., min_length=8, max_length=8),
    db=Depends(get_db)
):
    sess = db.query(SessionModel).filter(
        SessionModel.ref_code == ref_code
    ).first()
    if not sess:
        return templates.TemplateResponse(
            "save_error.html",
            {"request": request, "error_message": "Référence invalide ou session non active"}
        )
    if sess.status != "PAID":
        return templates.TemplateResponse(
            "save_error.html",
            {"request": request, "error_message": "La session doit être en PAID pour être mise en pause"}
        )
    if sess.status == "PAUSED":
        return templates.TemplateResponse(
            "save_error.html",
            {"request": request, "error_message": "La session est déjà en pause"}
        )
        
    now = datetime.utcnow()
    ecoule = (now - sess.start_at).total_seconds() / 60.0
    remaining = max(sess.minutes_left - ecoule, 0)
    sess.minutes_left = int(remaining)
    left = sess.minutes_total - sess.minutes_used
    sess.status = "PAUSED"
    station = db.query(Station).get(sess.station_id)
    if station:
        station.status = "FREE"
        db.add(station)
        
    db.add(sess)
    db.commit()
    return templates.TemplateResponse(
        "save.html",
        {
            "request": request,
            "ref_code": ref_code,
            "minutes_left": left,
        }
    )

# 12. Relancer une session
@app.post("/session/resume")
@app.post("/session/resume", response_class=HTMLResponse)
def resume_session(
    request: Request,
    ref_code: str = Form(..., min_length=8, max_length=8),
    db=Depends(get_db)
):
    sess = db.query(SessionModel).filter(
        SessionModel.ref_code == ref_code,
        SessionModel.status  == "PAUSED"
    ).first()
    if not sess:
        return templates.TemplateResponse(
            "save_error.html",
            {"request": request, "error_message": "Référence invalide ou session non mise en pause"}
        )
    # Trouver une station libre
    station = db.query(Station).filter(Station.status == "FREE").first()
    if not station:
        return templates.TemplateResponse(
            "save_error.html",
            {"request": request, "error_message": "Aucune station libre n'est disponible"}
        )
    station.status = "BUSY"
    db.add(station)
    sess.station_id = station.id
    now = datetime.utcnow()
    #sess.start_at = now
    #sess.end_at = now + timedelta(minutes=sess.minutes_left)
    sess.status = "PAID"
    db.add(sess)
    db.commit()

    return templates.TemplateResponse(
        "resume.html",
        {
            "request": request,
            "ref_code": ref_code,
            "minutes_left": sess.minutes_total - sess.minutes_used,
            "station_id": station.id
        }
    )
@app.on_event("startup")
async def startup_event():
    asyncio.create_task(session_watcher())
    
    
@app.get("/admin", response_class=HTMLResponse)
def admin_login_page(request: Request):
    return templates.TemplateResponse("admin.html", {"request": request})

@app.post("/admin/login")
async def admin_login(request: Request, payload: dict = Body(...)):
    username = payload.get("username")
    password = payload.get("password")

    if ADMINS.get(username) == password:
        # Authentification réussie
        request.session["admin_logged_in"] = True
        request.session["admin_user"] = username
        return {"status": "ok", "message": "Connexion réussie"}
    raise HTTPException(status_code=401, detail="Identifiants incorrects")
    
@app.get("/admin/dashboard", response_class=HTMLResponse)

def admin_dashboard(request: Request, db=Depends(get_db)):
    if not request.session.get("admin_logged_in"):
        # Non connecté : redirige vers la page de login
        return templates.TemplateResponse("admin.html", {"request": request, "message": "Veuillez vous connecter."})
    stations = db.query(Station).all()
    sessions = db.query(SessionModel).filter(SessionModel.status == "PAID").all()
    return templates.TemplateResponse("admin_dashboard.html", {
        "request": request,
        "stations": stations,
        "sessions": sessions
    })
@app.get("/admin/logout")
def admin_logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/admin", status_code=302)


@app.post("/admin/break-station")
def break_station(station_id: int = Form(...), db=Depends(get_db)):
    s = db.query(Station).get(station_id)
    if s:
        s.status = "BROKEN"
        db.add(s)
        db.commit()
    return RedirectResponse("/admin/dashboard", status_code=303)

@app.post("/admin/fix-station")
def fix_station(station_id: int = Form(...), db=Depends(get_db)):
    s = db.query(Station).get(station_id)
    if s:
        s.status = "FREE"
        db.add(s)
        db.commit()
    return RedirectResponse("/admin/dashboard", status_code=303)


@app.post("/admin/extend-session")
def extend_session_admin(
    ref_code: str = Form(...), 
    add_minutes: int = Form(...), 
    db=Depends(get_db)
):
    sess = db.query(SessionModel).filter(SessionModel.ref_code == ref_code).first()
    if sess and add_minutes > 0:
        sess.minutes_total += add_minutes
        sess.end_at += timedelta(minutes=add_minutes)
        db.add(sess)
        db.commit()
    return RedirectResponse("/admin/dashboard", status_code=303)


@app.post("/admin/delete-station")
def delete_station(station_id: int = Form(...), db=Depends(get_db)):
    s = db.query(Station).get(station_id)
    if s:
        db.delete(s)
        db.commit()
    return RedirectResponse("/admin/dashboard", status_code=303)


@app.get("/admin/session-details/{ref_code}", response_class=HTMLResponse)
def session_details(ref_code: str, request: Request, db=Depends(get_db)):
    sess = db.query(SessionModel).filter(SessionModel.ref_code == ref_code).first()
    return templates.TemplateResponse("admin_session_details.html", {"request": request, "sess": sess})

@app.get("/admin/station-games/{station_id}", response_class=HTMLResponse)
def station_games(station_id: int, request: Request, db=Depends(get_db)):
    station = db.query(Station).get(station_id)
    # À toi d’adapter selon la structure de tes jeux associés
    return templates.TemplateResponse("admin_station_games.html", {"request": request, "station": station, "games": station.games})

# GET + POST route

@app.get("/admin/valider-paiement")
async def afficher_formulaire(request: Request,auth=Depends(admin_required)):
    
    if not request.session.get("admin_logged_in"):
        # Non connecté : redirige vers la page de login
        return templates.TemplateResponse("admin.html", {"request": request, "message": "Veuillez vous connecter."})
    
    return templates.TemplateResponse("valider_paiement.html", {"request": request})


@app.post("/admin/valider-paiement")
async def generer_draft(request: Request,auth=Depends(admin_required)):
    form = await request.form()
    if not request.session.get("admin_logged_in"):
        # Non connecté : redirige vers la page de login
        return templates.TemplateResponse("admin.html", {"request": request, "message": "Veuillez vous connecter."})
    
    context = {
        "request": request,
        "txn_id": form.get("txn_id"),
        "operator": form.get("operator"),
        "amount": form.get("amount"),
        "client_name": form.get("client_name"),
        "client_phone": form.get("client_phone")
    }
    return templates.TemplateResponse("valider_paiement_draft.html", context)


@app.post("/admin/valider-paiement/confirm")
async def confirmer_paiement(
    request: Request,
    txn_id: str = Form(...),
    operator: str = Form(...),
    amount: int = Form(...),
    client_name: str = Form(...),
    client_phone: str = Form(...),
    auth=Depends(admin_required),
    db=Depends(get_db)
):
    if db.query(ValidatedPayment).filter_by(txn_id=txn_id).first():
        return templates.TemplateResponse("valider_paiement_draft.html", {
            "request": request,
            "txn_id": txn_id,
            "operator": operator,
            "amount": amount,
            "client_name": client_name,
            "client_phone": client_phone,
            "error": "❌ Ce paiement a déjà été validé !"
        })

    new_payment = ValidatedPayment(
        txn_id=txn_id,
        operator=operator,
        amount=amount,
        client_name=client_name,
        client_phone=client_phone,
        validated_by=request.session.get("admin_user", "unknown"),
        validated_at=datetime.utcnow(),
        is_used=False
    )
    db.add(new_payment)
    db.commit()

    return RedirectResponse("/admin/dashboard", status_code=303)


@app.get("/admin/sessions", response_class=HTMLResponse)
def sessions_en_cours(request: Request,auth=Depends(admin_required)):
    # ⚠️ À adapter selon ton ORM, ici exemple SQLAlchemy
    db = SessionLocal()
    
    sess = db.query(SessionModel).filter(SessionModel.status.in_(["PENDING", "PAID","PAUSED"])).all()
    db.close()
    return templates.TemplateResponse("admin_sessions.html", {
        "request": request,
        "sessions": sess,
    })
    
@app.get("/admin/machines", response_class=HTMLResponse)
def etat_machines(request: Request,auth=Depends(admin_required)):
    db = SessionLocal()
    stations = db.query(Station).all()   # à adapter selon ta table Station
    db.close()
    return templates.TemplateResponse("admin_machines.html", {
        "request": request,
        "stations": stations,
    })

@app.get("/admin/payments", response_class=HTMLResponse)
def consulter_paiements(request: Request,auth=Depends(admin_required)):
    db = SessionLocal()
    payments = db.query(ValidatedPayment).order_by(ValidatedPayment.validated_at.desc()).all()
    db.close()
    return templates.TemplateResponse("admin_payments.html", {
        "request": request,
        "payments": payments,
        "active_page": "payments"
    })

@app.get("/admin/historique", response_class=HTMLResponse)
def historique_admin(
    request: Request,
    history_type: str = Query("all"),
    poste_id: int = Query(None),
    auth=Depends(admin_required)
):
    db = SessionLocal()
    postes = db.query(Station).all()
    payment_logs = db.query(ValidatedPayment).order_by(ValidatedPayment.validated_at.desc()).all()
    poste_sessions = []

    if history_type == "poste" and poste_id:
        # On charge les paiements reliés AVANT fermeture de la DB !
        poste_sessions = (
        db.query(SessionModel)
        .options(joinedload(SessionModel.payment))   # <--- important
        .options(joinedload(SessionModel.offer))
        .filter(SessionModel.station_id == poste_id)
        .order_by(SessionModel.start_at.desc())
        .all()
        )
    db.close()
    return templates.TemplateResponse("admin_historique.html", {
        "request": request,
        "payment_logs": payment_logs,
        "selected": history_type,
        "poste_id": poste_id,
        "postes": postes,
        "poste_sessions": poste_sessions,
        "active_page": "historique"
    })
    
@app.get("/verifier-paiement", response_class=HTMLResponse)
def verifier_paiement(request: Request, txn_id: str = None, db=Depends(get_db)):
    payment = None
    if txn_id:
        payment = db.query(ValidatedPayment).filter_by(txn_id=txn_id).first()
    return templates.TemplateResponse("verifier_paiement.html", {
        "request": request,
        "payment": payment,
        "txn_id": txn_id,
    })
    
@app.post("/admin/pause-session")
def pause_session(
    ref_code: str = Form(..., min_length=8, max_length=8),
    db=Depends(get_db)
):
    sess = db.query(SessionModel).filter(SessionModel.ref_code == ref_code).first()
    if not sess or sess.status != "PAID":
        raise HTTPException(400, "Session non trouvée ou non active")
    
    Station = db.query(Station).get(sess.station_id)
    if not Station:
        raise HTTPException(404, "Station non trouvée")
    # Mettre la station en libre
    Station.status = "FREE"
    db.add(Station)
    sess.status = "PAUSED"
    db.add(sess)
    db.commit()
    return RedirectResponse(url="/admin/dashboard", status_code=303)
