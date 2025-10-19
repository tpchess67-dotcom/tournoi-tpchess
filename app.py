# Contenu COMPLET et PRÊT POUR DÉPLOIEMENT pour app.py
import os
from flask import Flask, render_template, request, redirect, url_for, flash, send_file, jsonify
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import math
from fpdf import FPDF
from io import BytesIO
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import func, cast, Date, exc # Imports for advanced queries
from sqlalchemy.orm import aliased          # Imports for advanced queries

# --- Configuration de l'Application ---
app = Flask(__name__)
basedir = os.path.abspath(os.path.dirname(__file__))

# Détection du moteur de BDD pour requêtes compatibles
DATABASE_URL = os.environ.get('DATABASE_URL')
IS_POSTGRES = DATABASE_URL and DATABASE_URL.startswith("postgres")

# Configuration de la BDD pour déploiement (Supabase/PostgreSQL) ou local (SQLite)
if IS_POSTGRES:
    app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URL.replace("postgres://", "postgresql://", 1)
    print(f"INFO: Using PostgreSQL database: {app.config['SQLALCHEMY_DATABASE_URI'][:30]}...")
else:
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'instance', 'tournoi.db')
    print("INFO: Using local SQLite database.")

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
# IMPORTANT: Change this secret key for production! Use a long, random string.
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'default-dev-secret-key-replace-in-prod')

# Create instance folder if it doesn't exist (for local SQLite)
instance_path = os.path.join(basedir, 'instance')
if not os.path.exists(instance_path):
    os.makedirs(instance_path)

db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = "Veuillez vous connecter pour accéder à cette page."
login_manager.login_message_category = "danger"

# --- Modèles de la Base de Données ---
# (Models: Joueur, EloHistory, Tournoi, Match, tournoi_joueurs table - unchanged)
class Joueur(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(256))
    prenom = db.Column(db.String(80), nullable=False)
    nom = db.Column(db.String(80), nullable=False)
    elo = db.Column(db.Integer, nullable=False, default=1500)
    is_admin = db.Column(db.Boolean, default=False)
    elo_history = db.relationship('EloHistory', backref='joueur', lazy=True, cascade="all, delete-orphan")

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class EloHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    joueur_id = db.Column(db.Integer, db.ForeignKey('joueur.id'), nullable=False)
    elo = db.Column(db.Integer, nullable=False)
    date = db.Column(db.DateTime, default=datetime.utcnow)
    note = db.Column(db.String(100), nullable=True)

class Tournoi(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nom = db.Column(db.String(120), nullable=False)
    date_creation = db.Column(db.DateTime, default=datetime.utcnow)
    nombre_rondes = db.Column(db.Integer, nullable=False)
    ronde_actuelle = db.Column(db.Integer, default=0)
    termine = db.Column(db.Boolean, default=False)
    joueurs = db.relationship('Joueur', secondary='tournoi_joueurs', backref='tournois')

tournoi_joueurs = db.Table('tournoi_joueurs',
    db.Column('joueur_id', db.ForeignKey('joueur.id'), primary_key=True),
    db.Column('tournoi_id', db.ForeignKey('tournoi.id'), primary_key=True)
)

class Match(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    tournoi_id = db.Column(db.Integer, db.ForeignKey('tournoi.id', ondelete='CASCADE'), nullable=False)
    ronde = db.Column(db.Integer, nullable=False)
    joueur1_id = db.Column(db.Integer, db.ForeignKey('joueur.id')) # Blancs
    joueur2_id = db.Column(db.Integer, db.ForeignKey('joueur.id')) # Noirs
    resultat = db.Column(db.Float)
    elo_gain_j1 = db.Column(db.Integer, default=0)
    elo_gain_j2 = db.Column(db.Integer, default=0)

    joueur1 = db.relationship('Joueur', foreign_keys=[joueur1_id])
    joueur2 = db.relationship('Joueur', foreign_keys=[joueur2_id])

# --- Fonctions Utilitaires ---
# (calculer_nouveau_elo - unchanged)
def calculer_nouveau_elo(elo_joueur, elo_adversaire, resultat):
    K = 32
    probabilite_attendue = 1 / (1 + math.pow(10, (elo_adversaire - elo_joueur) / 400))
    nouveau_elo = elo_joueur + K * (resultat - probabilite_attendue)
    return round(nouveau_elo)

# --- Routes d'Authentification ---
# (load_user, register, login, logout - unchanged)
@login_manager.user_loader
def load_user(user_id):
    return Joueur.query.get(int(user_id))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    if request.method == 'POST':
        username = request.form['username']
        prenom = request.form['prenom']
        nom = request.form['nom']
        password = request.form['password']
        elo_initial = 1500
        user_exists = Joueur.query.filter_by(username=username).first()
        if user_exists:
            flash('Ce nom d\'utilisateur est déjà pris.', 'danger')
            return redirect(url_for('register'))

        nouveau_joueur = Joueur(username=username, prenom=prenom, nom=nom, elo=elo_initial)
        nouveau_joueur.set_password(password)
        db.session.add(nouveau_joueur)
        db.session.commit()

        start_date = datetime(datetime.now().year, 10, 1)
        db.session.add(EloHistory(joueur_id=nouveau_joueur.id, elo=elo_initial, date=start_date, note="Création du compte"))
        db.session.commit()

        flash('Compte créé avec succès ! ELO de départ : 1500. Vous pouvez maintenant vous connecter.', 'success')
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated: return redirect(url_for('index'))
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = Joueur.query.filter_by(username=username).first()
        if user and user.check_password(password):
            login_user(user, remember=True)
            # Redirect to intended page or index
            next_page = request.args.get('next')
            return redirect(next_page or url_for('index'))
        else:
            flash('Nom d\'utilisateur ou mot de passe incorrect.', 'danger')
            return redirect(url_for('login'))
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Vous avez été déconnecté.', 'info')
    return redirect(url_for('index'))

@app.route('/profil')
@login_required
def profil():
    # (profil logic with weekly ELO calculation - unchanged)
    history_query = None
    try:
        if IS_POSTGRES:
            week_group = func.to_char(EloHistory.date, 'YYYY-WW')
            subquery = db.session.query(
                EloHistory.id, EloHistory.elo, EloHistory.date,
                func.row_number().over(
                    partition_by=week_group,
                    order_by=EloHistory.date.desc()
                ).label('rn')
            ).filter(EloHistory.joueur_id == current_user.id).subquery()
            history_query = db.session.query(subquery.c.elo, subquery.c.date) \
                                      .filter(subquery.c.rn == 1) \
                                      .order_by(subquery.c.date)
        else:
            week_group = func.strftime('%Y-%W', EloHistory.date)
            subquery = db.session.query(
                week_group.label('week_group'),
                func.max(EloHistory.date).label('max_date')
            ).filter(EloHistory.joueur_id == current_user.id) \
             .group_by('week_group') \
             .subquery()
            history_query = db.session.query(EloHistory.elo, EloHistory.date) \
                                      .join(subquery, EloHistory.date == subquery.c.max_date) \
                                      .order_by(EloHistory.date)
        history = history_query.all()
        if not history:
             # Ensure at least the starting ELO is shown
            start_history = EloHistory.query.filter_by(joueur_id=current_user.id, note="Création du compte").first()
            if start_history:
                 history = [(start_history.elo, start_history.date)]
            else: # Fallback if even the start history is missing
                 history = [(current_user.elo, datetime(datetime.now().year, 10, 1))]


    except exc.OperationalError:
        # Fallback if SQL functions are not supported
        history_raw = EloHistory.query.filter_by(joueur_id=current_user.id).order_by(EloHistory.date).all()
        if not history_raw:
            history = [(current_user.elo, datetime(datetime.now().year, 10, 1))]
        else:
            history = [(h.elo, h.date) for h in history_raw]

    labels = [h_date.strftime('%Y-%m-%d') for h_elo, h_date in history]
    data = [h_elo for h_elo, h_date in history]
    return render_template('profil.html', labels=labels, data=data)


# --- Routes de l'Application (Admin) ---
# (gerer_joueurs, modifier_elo, supprimer_joueur, creer_tournoi, supprimer_tournoi - unchanged)
@app.route('/joueurs')
@login_required
def gerer_joueurs():
    if not current_user.is_admin:
        return redirect(url_for('index'))
    joueurs = Joueur.query.order_by(Joueur.elo.desc()).all()
    return render_template('admin_joueurs.html', joueurs=joueurs)

@app.route('/joueur/modifier_elo/<int:id>', methods=['POST'])
@login_required
def modifier_elo(id):
    if not current_user.is_admin:
        flash('Action non autorisée.', 'danger')
        return redirect(url_for('gerer_joueurs'))

    joueur = Joueur.query.get_or_404(id)
    try:
        new_elo = int(request.form['elo'])
        if new_elo < 0:
            flash('L\'ELO ne peut pas être négatif.', 'danger')
        else:
            joueur.elo = new_elo
            db.session.add(EloHistory(joueur_id=joueur.id, elo=new_elo, note=f"Modif. Admin par {current_user.username}"))
            db.session.commit()
            flash(f'ELO de {joueur.prenom} {joueur.nom} mis à jour à {new_elo}.', 'success')
    except ValueError:
        flash('Valeur ELO invalide.', 'danger')

    return redirect(url_for('gerer_joueurs'))

@app.route('/joueur/supprimer/<int:id>')
@login_required
def supprimer_joueur(id):
    if not current_user.is_admin:
        flash('Action non autorisée.', 'danger')
        return redirect(url_for('index'))

    joueur = Joueur.query.get_or_404(id)
    Match.query.filter((Match.joueur1_id == id) | (Match.joueur2_id == id)).delete()
    db.session.delete(joueur) # EloHistory is deleted via cascade
    db.session.commit()
    flash('Joueur (et ses matchs/historique) supprimé.', 'success')
    return redirect(url_for('gerer_joueurs'))


@app.route('/tournoi/creer', methods=['POST'])
@login_required
def creer_tournoi():
    if not current_user.is_admin: return redirect(url_for('index'))
    nouveau_tournoi = Tournoi(nom=request.form['nom'], nombre_rondes=int(request.form['nombre_rondes']))
    db.session.add(nouveau_tournoi)
    db.session.commit()
    flash('Tournoi créé ! Vous pouvez maintenant le voir dans la liste des tournois actifs.', 'success')
    return redirect(url_for('index'))

@app.route('/tournoi/supprimer/<int:id>')
@login_required
def supprimer_tournoi(id):
    if not current_user.is_admin: return redirect(url_for('index'))
    tournoi = Tournoi.query.get_or_404(id)
    Match.query.filter_by(tournoi_id=id).delete()
    tournoi.joueurs = [] # Remove associations
    db.session.delete(tournoi)
    db.session.commit()
    flash(f'Le tournoi "{tournoi.nom}" a été supprimé.', 'success')
    return redirect(url_for('index'))

# --- Routes des Tournois (Publiques et Admin) ---
# (index, rejoindre_tournoi, retirer_joueur, gerer_tournoi, generer_ronde, sauver_resultats, export_pdf - unchanged)
@app.route('/')
def index():
    active_tournois = Tournoi.query.filter_by(termine=False).order_by(Tournoi.date_creation.desc()).all()
    finished_tournois = Tournoi.query.filter_by(termine=True).order_by(Tournoi.date_creation.desc()).all()
    joueurs_tries = Joueur.query.order_by(Joueur.elo.desc()).all()

    return render_template('index.html',
                           active_tournois=active_tournois,
                           finished_tournois=finished_tournois,
                           joueurs_tries=joueurs_tries)

@app.route('/tournoi/<int:id>/rejoindre', methods=['POST'])
@login_required
def rejoindre_tournoi(id):
    tournoi = Tournoi.query.get_or_404(id)
    if tournoi.ronde_actuelle > 0:
        flash("Les inscriptions sont fermées, le tournoi a déjà commencé.", 'danger')
        return redirect(url_for('index'))
    if current_user in tournoi.joueurs:
        flash("Vous êtes déjà inscrit à ce tournoi.", 'warning')
        return redirect(url_for('gerer_tournoi', id=id))

    tournoi.joueurs.append(current_user)
    db.session.commit()
    flash(f"Vous êtes maintenant inscrit au tournoi '{tournoi.nom}' !", 'success')
    return redirect(url_for('gerer_tournoi', id=id))

@app.route('/tournoi/<int:tournoi_id>/retirer_joueur/<int:joueur_id>')
@login_required
def retirer_joueur(tournoi_id, joueur_id):
    if not current_user.is_admin:
        flash('Action non autorisée.', 'danger')
        return redirect(url_for('gerer_tournoi', id=tournoi_id))

    tournoi = Tournoi.query.get_or_404(tournoi_id)
    if tournoi.termine:
        flash('Le tournoi est terminé, impossible de retirer un joueur.', 'warning')
        return redirect(url_for('gerer_tournoi', id=tournoi_id))

    joueur = Joueur.query.get_or_404(joueur_id)

    if joueur in tournoi.joueurs:
        tournoi.joueurs.remove(joueur)
        db.session.commit()
        flash(f'{joueur.prenom} {joueur.nom} a été retiré(e) du tournoi. Il/Elle ne sera plus apparié(e).', 'success')
    else:
        flash('Ce joueur n\'est pas (ou plus) dans le tournoi.', 'warning')

    return redirect(url_for('gerer_tournoi', id=tournoi_id))


@app.route('/tournoi/<int:id>', methods=['GET', 'POST'])
@login_required
def gerer_tournoi(id):
    tournoi = Tournoi.query.get_or_404(id)

    if request.method == 'POST': # Manual registration (Admin)
        if not current_user.is_admin:
            flash('Action non autorisée.', 'danger')
            return redirect(url_for('gerer_tournoi', id=id))
        ids_joueurs_a_inscrire = request.form.getlist('joueurs_ids')
        tournoi.joueurs = [] # Reset and add selected
        for joueur_id in ids_joueurs_a_inscrire:
            joueur = Joueur.query.get(joueur_id)
            if joueur: tournoi.joueurs.append(joueur)
        db.session.commit()
        flash('Inscriptions mises à jour.', 'success')
        return redirect(url_for('gerer_tournoi', id=id))

    tous_les_joueurs = Joueur.query.order_by(Joueur.nom).all()
    joueurs_inscrits_ids = {j.id for j in tournoi.joueurs}

    # Score calculation logic handling withdrawn players
    matchs_du_tournoi = Match.query.filter_by(tournoi_id=id).all()
    all_player_ids_in_tournoi = set(j.id for j in tournoi.joueurs)
    for m in matchs_du_tournoi:
        if m.joueur1_id: all_player_ids_in_tournoi.add(m.joueur1_id)
        if m.joueur2_id: all_player_ids_in_tournoi.add(m.joueur2_id)
    scores = {pid: 0.0 for pid in all_player_ids_in_tournoi}
    for m in matchs_du_tournoi:
        if m.resultat is not None:
            if m.joueur1_id in scores: scores[m.joueur1_id] += m.resultat
            if m.joueur2_id in scores: scores[m.joueur2_id] += (1.0 - m.resultat)

    # Sort CURRENT participants for display
    joueurs_tries = sorted(tournoi.joueurs, key=lambda j: (scores.get(j.id, 0.0), j.elo), reverse=True)

    matchs_par_ronde = {}
    for r in range(1, tournoi.ronde_actuelle + 1):
        matchs_par_ronde[r] = Match.query.filter_by(tournoi_id=id, ronde=r).all()

    return render_template('tournoi.html', tournoi=tournoi, tous_les_joueurs=tous_les_joueurs, joueurs_inscrits_ids=joueurs_inscrits_ids, scores=scores, joueurs_tries=joueurs_tries, matchs_par_ronde=matchs_par_ronde)


@app.route('/tournoi/<int:id>/generer_ronde')
@login_required
def generer_ronde(id):
    if not current_user.is_admin: return redirect(url_for('gerer_tournoi', id=id))
    tournoi = Tournoi.query.get_or_404(id)
    if tournoi.termine or tournoi.ronde_actuelle >= tournoi.nombre_rondes:
        flash("Tournoi terminé ou max rondes atteint.", "warning")
        return redirect(url_for('gerer_tournoi', id=id))
    if tournoi.ronde_actuelle > 0:
        matchs_ronde_precedente = Match.query.filter_by(tournoi_id=id, ronde=tournoi.ronde_actuelle).all()
        if any(m.resultat is None for m in matchs_ronde_precedente if m.joueur2_id): # Only check non-bye matches
            flash("Veuillez entrer tous les résultats de la ronde actuelle.", "danger")
            return redirect(url_for('gerer_tournoi', id=id))

    tournoi.ronde_actuelle += 1

    # Pairings use current tournoi.joueurs
    scores = {j.id: 0.0 for j in tournoi.joueurs}
    matchs_du_tournoi = Match.query.filter_by(tournoi_id=id).all()
    for m in matchs_du_tournoi:
        if m.resultat is not None:
            if m.joueur1_id in scores: scores[m.joueur1_id] += m.resultat
            if m.joueur2_id in scores: scores[m.joueur2_id] += (1.0 - m.resultat)

    joueurs_a_apparier = sorted(tournoi.joueurs, key=lambda j: (scores.get(j.id, 0.0), j.elo), reverse=True)
    adversaires_deja_rencontres = {j.id: set() for j in tournoi.joueurs}
    for m in matchs_du_tournoi:
        if m.joueur1_id and m.joueur2_id:
            # Only consider encounters between currently active players for future pairings
            if m.joueur1_id in adversaires_deja_rencontres:
                adversaires_deja_rencontres[m.joueur1_id].add(m.joueur2_id)
            if m.joueur2_id in adversaires_deja_rencontres:
                adversaires_deja_rencontres[m.joueur2_id].add(m.joueur1_id)


    appariements = []
    joueurs_non_apparies = list(joueurs_a_apparier)
    while len(joueurs_non_apparies) > 1:
        j1 = joueurs_non_apparies.pop(0) # White
        # Find opponent j2 hasn't played yet
        j2_trouve = next((j for j in joueurs_non_apparies if j.id not in adversaires_deja_rencontres[j1.id]), None)
        if not j2_trouve: # If all possible opponents already played, force pairing
             j2_trouve = joueurs_non_apparies.pop(0) # Black
        else: # Found suitable opponent
             joueurs_non_apparies.remove(j2_trouve)
        appariements.append((j1, j2_trouve)) # (White, Black)

    for j1, j2 in appariements:
        db.session.add(Match(tournoi_id=id, ronde=tournoi.ronde_actuelle, joueur1_id=j1.id, joueur2_id=j2.id))
    if joueurs_non_apparies: # Handle bye
        joueur_exempt = joueurs_non_apparies[0]
        db.session.add(Match(tournoi_id=id, ronde=tournoi.ronde_actuelle, joueur1_id=joueur_exempt.id, joueur2_id=None, resultat=1.0))
        # Update ELO for bye (treat as draw against self)
        # Check if player exists before updating ELO
        joueur_obj = Joueur.query.get(joueur_exempt.id)
        if joueur_obj:
            elo_avant = joueur_obj.elo
            joueur_obj.elo = calculer_nouveau_elo(elo_avant, elo_avant, 0.5)
            db.session.add(EloHistory(joueur_id=joueur_obj.id, elo=joueur_obj.elo, note=f"Tournoi {tournoi.nom} R{tournoi.ronde_actuelle} (Bye)"))


    db.session.commit()
    flash(f"Ronde {tournoi.ronde_actuelle} générée !", "success")
    return redirect(url_for('gerer_tournoi', id=id))

@app.route('/tournoi/<int:id>/resultats', methods=['POST'])
@login_required
def sauver_resultats(id):
    if not current_user.is_admin: return redirect(url_for('gerer_tournoi', id=id))
    tournoi = Tournoi.query.get_or_404(id)
    ronde = tournoi.ronde_actuelle
    matchs_ronde_actuelle = Match.query.filter_by(tournoi_id=id, ronde=ronde).all()

    for match in matchs_ronde_actuelle:
        if match.joueur2_id is not None: # Only process non-bye matches
            resultat_form = request.form.get(f'resultat_{match.id}')
            if resultat_form is not None:
                match.resultat = float(resultat_form)

    db.session.commit() # Save results first

    # Calculate ELO changes
    for match in matchs_ronde_actuelle:
        if match.resultat is not None and match.joueur2_id is not None:
            j1 = Joueur.query.get(match.joueur1_id)
            j2 = Joueur.query.get(match.joueur2_id)
            # Proceed only if both players still exist
            if j1 and j2:
                elo_j1_avant = j1.elo
                elo_j2_avant = j2.elo
                resultat_j1 = match.resultat
                resultat_j2 = 1.0 - match.resultat

                j1.elo = calculer_nouveau_elo(elo_j1_avant, elo_j2_avant, resultat_j1)
                j2.elo = calculer_nouveau_elo(elo_j2_avant, elo_j1_avant, resultat_j2)

                match.elo_gain_j1 = j1.elo - elo_j1_avant
                match.elo_gain_j2 = j2.elo - elo_j2_avant

                db.session.add(EloHistory(joueur_id=j1.id, elo=j1.elo, note=f"Tournoi {tournoi.nom} R{ronde}"))
                db.session.add(EloHistory(joueur_id=j2.id, elo=j2.elo, note=f"Tournoi {tournoi.nom} R{ronde}"))

    if tournoi.ronde_actuelle == tournoi.nombre_rondes:
        tournoi.termine = True

    db.session.commit() # Save ELO changes and match gains
    flash(f"Résultats de la ronde {ronde} enregistrés et ELO mis à jour !", "success")
    return redirect(url_for('gerer_tournoi', id=id))


# --- PDF ---
# (export_pdf function using updated player_data logic - unchanged)
@app.route('/tournoi/<int:id>/export_pdf')
@login_required
def export_pdf(id):
    tournoi = Tournoi.query.get_or_404(id)
    # Use all players who participated, even if withdrawn
    all_matchs = Match.query.filter_by(tournoi_id=id).order_by(Match.ronde).all()
    all_player_ids = set()
    for m in all_matchs:
        if m.joueur1_id: all_player_ids.add(m.joueur1_id)
        if m.joueur2_id: all_player_ids.add(m.joueur2_id)
    all_players_in_tournoi = Joueur.query.filter(Joueur.id.in_(all_player_ids)).all()

    player_data = {}
    for j in all_players_in_tournoi:
        player_data[j.id] = {
            'nom': f"{j.prenom} {j.nom}",
            'total_points': 0.0,
            'rondes': {r: {'resultat': '-', 'couleur': '', 'elo_gain': 0} for r in range(1, tournoi.nombre_rondes + 1)}
        }

    for match in all_matchs:
        ronde = match.ronde
        if match.joueur1_id not in player_data or (match.joueur2_id and match.joueur2_id not in player_data):
             continue # Skip match if a player was deleted entirely

        if match.joueur2_id:
            j1_id, j2_id = match.joueur1_id, match.joueur2_id
            if match.resultat is not None:
                res_j1, res_j2 = match.resultat, 1.0 - match.resultat
                player_data[j1_id]['total_points'] += res_j1
                player_data[j2_id]['total_points'] += res_j2
                player_data[j1_id]['rondes'][ronde] = {'resultat': res_j1, 'couleur': 'B', 'elo_gain': match.elo_gain_j1 or 0}
                player_data[j2_id]['rondes'][ronde] = {'resultat': res_j2, 'couleur': 'N', 'elo_gain': match.elo_gain_j2 or 0}

        elif match.joueur1_id and not match.joueur2_id: # Bye case
            j1_id = match.joueur1_id
            if match.resultat == 1.0:
                player_data[j1_id]['total_points'] += 1.0
                player_data[j1_id]['rondes'][ronde] = {'resultat': 1.0, 'couleur': 'BYE', 'elo_gain': 0}


    sorted_players = sorted(player_data.values(), key=lambda x: x['total_points'], reverse=True)

    class PDF(FPDF):
        def header(self):
            self.add_font('DejaVu', '', 'DejaVuSans.ttf', uni=True)
            self.set_font('DejaVu', '', 16)
            self.cell(0, 10, f'Grille de Classement - "{tournoi.nom}"', 0, 1, 'C')
            self.set_font('DejaVu', '', 10)
            self.cell(0, 7, f'Tournoi en {tournoi.nombre_rondes} rondes. Statut: {"Terminé" if tournoi.termine else "En cours"}', 0, 1, 'C')
            self.ln(5)
        def footer(self):
            self.set_y(-15)
            self.set_font('DejaVu', '', 8)
            self.cell(0, 10, f'Page {self.page_no()}', 0, 0, 'C')

    pdf = PDF(orientation='L', unit='mm', format='A4') # Landscape mode
    pdf.add_page()
    pdf.add_font('DejaVu', '', 'DejaVuSans.ttf', uni=True)
    pdf.set_font('DejaVu', '', 10)

    # Calculate column widths dynamically
    available_width = pdf.w - pdf.l_margin - pdf.r_margin
    col_width_joueur = 60
    col_width_total = 15
    col_width_elo = 20
    remaining_width = available_width - col_width_joueur - col_width_total - col_width_elo
    col_width_ronde = remaining_width / tournoi.nombre_rondes if tournoi.nombre_rondes > 0 else 0

    # Table Header
    pdf.set_font('DejaVu', '', 8)
    pdf.cell(col_width_joueur, 10, 'Joueur', 1, 0, 'C')
    for r in range(1, tournoi.nombre_rondes + 1):
        pdf.cell(col_width_ronde, 10, f'R {r}', 1, 0, 'C')
    pdf.cell(col_width_total, 10, 'Total', 1, 0, 'C')
    pdf.cell(col_width_elo, 10, 'Gain ELO', 1, 1, 'C')

    # Table Body
    pdf.set_font('DejaVu', '', 9)
    for i, player in enumerate(sorted_players):
        pdf.cell(col_width_joueur, 10, f"{i+1}. {player['nom']}", 1)
        elo_gain_cumul = 0
        for r in range(1, tournoi.nombre_rondes + 1):
            data = player['rondes'][r]
            # Format result correctly
            res_str = str(data['resultat'])
            if res_str == '1.0': res_str = '1'
            elif res_str == '0.5': res_str = '½'
            elif res_str == '0.0': res_str = '0'

            cell_text = f"{res_str} ({data['couleur']})"
            if data['couleur'] == 'BYE': cell_text = "1 (BYE)"
            elif data['couleur'] == '': cell_text = "-"

            elo_gain_cumul += data['elo_gain']
            pdf.cell(col_width_ronde, 10, cell_text, 1, 0, 'C')

        pdf.cell(col_width_total, 10, f"{player['total_points']}", 1, 0, 'C')
        pdf.cell(col_width_elo, 10, f"{'+' if elo_gain_cumul > 0 else ''}{elo_gain_cumul}", 1, 1, 'C')

    pdf_bytes = pdf.output()
    return send_file(BytesIO(pdf_bytes), as_attachment=True, download_name=f'classement_{tournoi.nom}.pdf', mimetype='application/pdf')


# --- Commandes CLI ---
# (init-db, create-admin - unchanged)
@app.cli.command("init-db")
def init_db_command():
    """Creates the database tables."""
    db.create_all()
    print("Database initialized.")

@app.cli.command("create-admin")
def create_admin_command():
    """Creates the initial admin user."""
    username = input("Admin username: ")
    password = input("Admin password: ")
    prenom = input("First name: ")
    nom = input("Last name: ")

    user_exists = Joueur.query.filter_by(username=username).first()
    if user_exists:
        print("This username already exists.")
        return

    admin = Joueur(username=username, prenom=prenom, nom=nom, elo=1500, is_admin=True)
    admin.set_password(password)
    db.session.add(admin)
    db.session.commit()
    start_date = datetime(datetime.now().year, 10, 1)
    db.session.add(EloHistory(joueur_id=admin.id, elo=admin.elo, date=start_date, note="Création du compte (Admin)"))
    db.session.commit()
    print(f"Administrator '{username}' created successfully!")


# --- Run ---
if __name__ == '__main__':
    # Create tables if running with `python app.py` and db doesn't exist
    with app.app_context():
        # Check if tables exist before creating, especially for local SQLite
        inspector = db.inspect(db.engine)
        if not inspector.has_table("joueur"): # Check for one table
             print("Creating database tables...")
             db.create_all()
             print("Tables created.")
        else:
             print("Database tables already exist.")
    app.run(debug=True) # debug=True for development only!
