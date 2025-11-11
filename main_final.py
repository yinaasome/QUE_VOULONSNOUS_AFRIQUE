import streamlit as st
from streamlit_javascript import st_javascript
import pymongo
from pymongo import MongoClient
import uuid
import random
import pandas as pd
import os
import altair as alt
from textblob import TextBlob
import numpy as np
from datetime import datetime, timedelta
import time
from PIL import Image
import base64

# 🛠️ Configuration de la page
st.set_page_config(page_title="Wiki Survey", layout="wide", page_icon="🗳️")

# === Configuration MongoDB ===
MONGO_URI = "mongodb://localhost:27017/"
#MONGO_URI = "mongodb://mongo:JiwSbeZEXWiILqHARYsOnvkCOenDSKoY@shuttle.proxy.rlwy.net:28806"
DB_NAME = "Africa"

# 🔧 FONCTION POUR CONVERTIR LES ObjectId
def convertir_objectid_pour_streamlit(donnees):
    """Convertit les ObjectId MongoDB en string pour éviter les erreurs Arrow/Streamlit"""
    if isinstance(donnees, list):
        for item in donnees:
            if isinstance(item, dict):
                for key, value in item.items():
                    if hasattr(value, '__class__') and 'ObjectId' in str(type(value)):
                        item[key] = str(value)
    elif isinstance(donnees, dict):
        for key, value in donnees.items():
            if hasattr(value, '__class__') and 'ObjectId' in str(type(value)):
                donnees[key] = str(value)
    return donnees

# --- Connexion à MongoDB ---
@st.cache_resource
def get_db_connection():
    """Obtenir une connexion à MongoDB"""
    try:
        client = MongoClient(MONGO_URI)
        db = client[DB_NAME]
        return db
    except Exception as e:
        st.error(f"Erreur de connexion à MongoDB: {e}")
        return None

# === Création des collections et index ===
def init_database():
    """Initialiser la structure de la base MongoDB"""
    try:
        db = get_db_connection()

        # Créer les collections si elles n'existent pas
        collections = [
            "navigateur", "login", "question",
            "idees", "vote", "commentaire",
            "profil", "sentiment_analytics"
        ]

        for collection in collections:
            if collection not in db.list_collection_names():
                db.create_collection(collection)

        # Créer les index
        db.login.create_index("email", unique=True)
        db.idees.create_index("id_question")
        db.vote.create_index([("id_navigateur", 1), ("id_question", 1)], unique=True)
        db.profil.create_index("id_navigateur", unique=True)
        db.sentiment_analytics.create_index("id_question", unique=True)

        # Insérer des données de test (administrateur et utilisateur avec droit d'image)
        db.login.update_one(
            {"email": "admin@test.com"},
            {"$set": {
                "email": "admin@test.com",
                "mot_de_passe": "admin123", 
                "date_creation": datetime.now()
            }},
            upsert=True
        )
        
        # AJOUT DE L'UTILISATEUR "yinnaasome@gmail.com" AVEC LE DROIT D'IMAGE
        db.login.update_one(
            {"email": "yinnaasome@gmail.com"},
            {"$set": {
                "email": "yinnaasome@gmail.com",
                "mot_de_passe": "abc", 
                "date_creation": datetime.now()
            }},
            upsert=True
        )

        print("✅ Base MongoDB initialisée avec succès")
        return True

    except Exception as e:
        print(f"❌ Erreur initialisation MongoDB: {e}")
        return False

# 🔧 FONCTION DE VÉRIFICATION ET CORRECTION DES DONNÉES
def verifier_et_corriger_donnees():
    """Vérifie et corrige les données manquantes dans la base"""
    db = get_db_connection()
    
    # Corriger les idées sans champ creer_par_utilisateur
    idees_sans_champ = db.idees.count_documents({"creer_par_utilisateur": {"$exists": False}})
    if idees_sans_champ > 0:
        db.idees.update_many(
            {"creer_par_utilisateur": {"$exists": False}},
            {"$set": {"creer_par_utilisateur": "non"}}
        )
        print(f"✅ Corrigé {idees_sans_champ} idées sans champ 'creer_par_utilisateur'")
    
    # Corriger les idées sans sentiment
    idees_sans_sentiment = db.idees.count_documents({"sentiment_score": {"$exists": False}})
    if idees_sans_sentiment > 0:
        db.idees.update_many(
            {"sentiment_score": {"$exists": False}},
            {"$set": {
                "sentiment_score": 0.0,
                "sentiment_label": "Non analysé"
            }}
        )
        print(f"✅ Corrigé {idees_sans_sentiment} idées sans analyse de sentiment")

# === Analyse de sentiment ===
def analyze_sentiment(text):
    """Analyser le sentiment d'un texte avec TextBlob"""
    try:
        blob = TextBlob(text)
        polarity = blob.sentiment.polarity

        if polarity > 0.1:
            label = "Positif"
        elif polarity < -0.1:
            label = "Négatif"
        else:
            label = "Neutre"

        return polarity, label
    except:
        return 0.0, "Neutre"

def update_sentiment_analytics(question_id):
    """Mettre à jour les analytics de sentiment pour une question"""
    try:
        db = get_db_connection()

        # Calculer les stats pour les idées
        idees_stats_cursor = db.idees.aggregate([
            {"$match": {"id_question": question_id}},
            {"$group": {
                "_id": None,
                "avg_sentiment": {"$avg": "$sentiment_score"},
                "positifs": {"$sum": {"$cond": [{"$eq": ["$sentiment_label", "Positif"]}, 1, 0]}},
                "negatifs": {"$sum": {"$cond": [{"$eq": ["$sentiment_label", "Négatif"]}, 1, 0]}},
                "neutres": {"$sum": {"$cond": [{"$eq": ["$sentiment_label", "Neutre"]}, 1, 0]}}
            }}
        ])
        idees_stats = next(idees_stats_cursor, {})

        # Calculer les stats pour les commentaires
        commentaires_stats_cursor = db.commentaire.aggregate([
            {"$match": {"id_question": question_id}},
            {"$group": {
                "_id": None,
                "avg_sentiment": {"$avg": "$sentiment_score"},
                "positifs": {"$sum": {"$cond": [{"$eq": ["$sentiment_label", "Positif"]}, 1, 0]}},
                "negatifs": {"$sum": {"$cond": [{"$eq": ["$sentiment_label", "Négatif"]}, 1, 0]}},
                "neutres": {"$sum": {"$cond": [{"$eq": ["$sentiment_label", "Neutre"]}, 1, 0]}}
            }}
        ])
        commentaires_stats = next(commentaires_stats_cursor, {})

        # Insérer ou mettre à jour les analytics
        db.sentiment_analytics.update_one(
            {"id_question": question_id},
            {"$set": {
                "moyenne_sentiment_idees": idees_stats.get("avg_sentiment", 0),
                "moyenne_sentiment_commentaires": commentaires_stats.get("avg_sentiment", 0),
                "total_idees_positives": idees_stats.get("positifs", 0),
                "total_idees_negatives": idees_stats.get("negatifs", 0),
                "total_idees_neutres": idees_stats.get("neutres", 0),
                "total_commentaires_positifs": commentaires_stats.get("positifs", 0),
                "total_commentaires_negatifs": commentaires_stats.get("negatifs", 0),
                "total_commentaires_neutres": commentaires_stats.get("neutres", 0),
                "derniere_mise_a_jour": datetime.now()
            }},
            upsert=True
        )

    except Exception as e:
        st.error(f"Erreur mise à jour analytics: {e}")

# Initialisation de la base
if not init_database():
    st.error("❌ Erreur initialisation MongoDB")
    st.stop()

# 🔧 VÉRIFICATION DES DONNÉES
verifier_et_corriger_donnees()

# Initialiser les clés nécessaires dans session_state
if "page" not in st.session_state:
    st.session_state["page"] = "home"

if "id_navigateur" not in st.session_state:
    st.session_state["id_navigateur"] = None

if "auto_refresh" not in st.session_state:
    st.session_state.auto_refresh = False

if "auth" not in st.session_state:
    st.session_state.auth = False

if "utilisateur_id" not in st.session_state:
    st.session_state.utilisateur_id = None

if "email" not in st.session_state:
    st.session_state.email = None

# --- ID navigateur ---
def get_navigateur_id():
    js_code = """
        const existing = localStorage.getItem("id_navigateur");
        if (existing) {
            existing;
        } else {
            const newId = crypto.randomUUID();
            localStorage.setItem("id_navigateur", newId);
            newId;
        }
    """
    return st_javascript(js_code)

def detect_navigateur():
    js_code = "navigator.userAgent;"
    agent = st_javascript(js_code)
    if agent:
        if "Chrome" in agent and "Edg" not in agent:
            return "Chrome"
        elif "Firefox" in agent:
            return "Firefox"
        elif "Edg" in agent:
            return "Edge"
        elif "Safari" in agent and "Chrome" not in agent:
            return "Safari"
    return "Inconnu"

def init_navigateur():
    if not st.session_state["id_navigateur"]:
        id_navigateur = get_navigateur_id()
        if id_navigateur and len(id_navigateur) > 100:
            id_navigateur = id_navigateur[:100]  # Tronquer si nécessaire
        navigateur_nom = detect_navigateur()
        if id_navigateur:
            st.session_state["id_navigateur"] = id_navigateur
            db = get_db_connection()
            db.navigateur.update_one(
                {"id_navigateur": id_navigateur},
                {"$set": {
                    "id_navigateur": id_navigateur,
                    "navigateur": navigateur_nom,
                    "date_creation": datetime.now()
                }},
                upsert=True
            )

# Appel obligatoire
init_navigateur()

# =============================================================
# === FONCTIONS D'AUTHENTIFICATION ===
# =============================================================

def creer_compte():
    """Page de création de compte pour les nouveaux utilisateurs."""
    st.subheader("Créez votre compte pour proposer une question")
    db = get_db_connection()

    email_reg = st.text_input("Email", key="email_reg")
    mot_de_passe_reg = st.text_input("Mot de passe", type="password", key="pass_reg")
    mot_de_passe_conf = st.text_input("Confirmer le mot de passe", type="password", key="pass_conf")

    if st.button("Créer le compte"):
        if not email_reg or not mot_de_passe_reg or not mot_de_passe_conf:
            st.error("Veuillez remplir tous les champs.")
            return

        if mot_de_passe_reg != mot_de_passe_conf:
            st.error("Les mots de passe ne correspondent pas.")
            return

        # Vérifier si l'email existe déjà 
        if db.login.find_one({"email": email_reg}):
            st.error("Cet email est déjà utilisé. Veuillez vous connecter.")
            return

        # Enregistrer le nouvel utilisateur
        nouvel_utilisateur = {
            "email": email_reg,
            "mot_de_passe": mot_de_passe_reg,
            "date_creation": datetime.now()
        }
        user_id = db.login.insert_one(nouvel_utilisateur).inserted_id

        # Connexion automatique après la création
        st.session_state.auth = True
        st.session_state.utilisateur_id = str(user_id)
        st.session_state.email = email_reg
        st.success(f"✅ Compte créé et connexion réussie ! Bienvenue {st.session_state.email} !")
        st.rerun()

def login_page():
    """Interface de connexion pour les utilisateurs existants."""
    st.subheader("Connectez-vous pour proposer une question")
    db = get_db_connection()
    email = st.text_input("Email", key="email_login")
    mot_de_passe = st.text_input("Mot de passe", type="password", key="pass_login")

    if st.button("Se connecter"):
        utilisateur = db.login.find_one({
            "email": email,
            "mot_de_passe": mot_de_passe
        })

        if utilisateur:
            st.session_state.auth = True
            st.session_state.utilisateur_id = str(utilisateur["_id"])
            st.session_state.email = utilisateur["email"]
            st.success(f"✅ Bienvenue {st.session_state.email} !")
            time.sleep(1)
            st.rerun()
        else:
            st.error("❌ Identifiants incorrects")

def authentication_flow():
    """Gère la connexion et la création de compte via des onglets"""
    tab_login, tab_register = st.tabs(["🔒 Se connecter", "✏️ Créer un compte"])

    with tab_login:
        login_page()

    with tab_register:
        creer_compte()

# === Fonctions principales adaptées pour MongoDB ===
def creer_question():
    st.header("✏️ Créer une nouvelle question")

    # Vérifier si l'utilisateur est connecté, sinon afficher la page d'authentification
    if not st.session_state.get("auth"):
        st.info("Veuillez vous connecter ou créer un compte pour proposer une question.")
        authentication_flow()
        return

    with st.form("form_question"):
        question = st.text_input("Votre question :")
        idee1 = st.text_input("Idée 1 :")
        idee2 = st.text_input("Idée 2 :")
        submitted = st.form_submit_button("Créer")

        if submitted and question.strip() and idee1.strip() and idee2.strip():
            db = get_db_connection()

            # Insérer la question
            question_data = {
                "question": question,
                "createur_id": st.session_state.utilisateur_id,
                "date_creation": datetime.now()
            }
            question_id = db.question.insert_one(question_data).inserted_id

            # Analyser sentiment des idées
            score1, label1 = analyze_sentiment(idee1)
            score2, label2 = analyze_sentiment(idee2)

            # Insérer les idées
            db.idees.insert_many([
                {
                    "id_question": question_id,
                    "idee_texte": idee1,
                    "creer_par_utilisateur": "non",
                    "date_creation": datetime.now(),
                    "sentiment_score": float(score1),
                    "sentiment_label": label1
                },
                {
                    "id_question": question_id,
                    "idee_texte": idee2,
                    "creer_par_utilisateur": "non",
                    "date_creation": datetime.now(),
                    "sentiment_score": float(score2),
                    "sentiment_label": label2
                }
            ])

            # Mettre à jour les analytics
            update_sentiment_analytics(question_id)

            st.success("✅ Question et idées enregistrées avec analyse de sentiment.")
        elif submitted:
            st.error("Veuillez remplir tous les champs.")

def participer():
    st.header("🗳️ Participer aux votes")
    db = get_db_connection()

    # Récupérer toutes les questions
    all_questions = list(db.question.find({}, {"_id": 1, "question": 1}))

    # Récupérer les questions déjà votées
    voted_q_ids = [v["id_question"] for v in db.vote.find(
        {"id_navigateur": st.session_state.id_navigateur},
        {"id_question": 1}
    )]

    # Questions disponibles pour le vote
    questions = [q for q in all_questions if q["_id"] not in voted_q_ids]

    if 'current_question_index' not in st.session_state:
        st.session_state.current_question_index = 0

    if st.session_state.current_question_index >= len(questions):
        st.success("✅ Vous avez terminé toutes les questions disponibles.")
        afficher_formulaire_profil()
        return

    selected_question = questions[st.session_state.current_question_index]
    #st.subheader(f"Question : {selected_question['question']}")
    st.subheader(selected_question['question'])
    question_id = selected_question["_id"]

    # Récupérer les idées pour cette question
    ideas = list(db.idees.find({"id_question": question_id}, {"_id": 1, "idee_texte": 1}))

    if len(ideas) >= 2:
        choices = random.sample(ideas, 2)
        col1, col2 = st.columns(2)
        with col1:
            if st.button(choices[0]['idee_texte'], key=f"btn1_{question_id}"):
                enregistrer_vote(choices[0]['_id'], choices[1]['_id'], question_id)
                st.session_state.current_question_index += 1
                st.rerun()
        with col2:
            if st.button(choices[1]['idee_texte'], key=f"btn2_{question_id}"):
                enregistrer_vote(choices[1]['_id'], choices[0]['_id'], question_id)
                st.session_state.current_question_index += 1
                st.rerun()

    # Nouvelle idée avec analyse de sentiment
    st.markdown("### 💡 Proposer une nouvelle idée")
    nouvelle_idee_key = f"nouvelle_idee_{question_id}"

    if st.session_state.get(f"idee_envoyee_{question_id}"):
        st.session_state[nouvelle_idee_key] = ""
        del st.session_state[f"idee_envoyee_{question_id}"]

    nouvelle_idee = st.text_area("Votre idée innovante :", key=nouvelle_idee_key, height=80)

    if st.button("➕ Soumettre l'idée", key=f"btn_idee_{question_id}"):
        if nouvelle_idee.strip():
            score, label = analyze_sentiment(nouvelle_idee)
            db.idees.insert_one({
                "id_question": question_id,
                "idee_texte": nouvelle_idee.strip(),
                "creer_par_utilisateur": "oui",
                "date_creation": datetime.now(),
                "sentiment_score": float(score),
                "sentiment_label": label
            })

            # Mettre à jour analytics
            update_sentiment_analytics(question_id)

            st.success(f"✅ Idée ajoutée (Sentiment: {label}) !")
            st.session_state[f"idee_envoyee_{question_id}"] = True
            st.rerun()

    # Commentaire avec analyse de sentiment
    st.markdown("### 💬 Ajouter un commentaire")
    comment_key = f"commentaire_{question_id}"

    if st.session_state.get(f"commentaire_envoye_{question_id}"):
        st.session_state[comment_key] = ""
        del st.session_state[f"commentaire_envoye_{question_id}"]

    commentaire = st.text_area("Votre opinion :", key=comment_key, height=80)

    if st.button("💾 Ajouter commentaire", key=f"btn_comment_{question_id}"):
        if commentaire.strip():
            score, label = analyze_sentiment(commentaire)
            db.commentaire.insert_one({
                "id_navigateur": st.session_state["id_navigateur"],
                "id_question": question_id,
                "commentaire": commentaire.strip(),
                "date_creation": datetime.now(),
                "sentiment_score": float(score),
                "sentiment_label": label
            })

            # Mettre à jour analytics
            update_sentiment_analytics(question_id)

            st.success(f"💬 Commentaire ajouté (Sentiment: {label}) !")
            st.session_state[f"commentaire_envoye_{question_id}"] = True
            st.rerun()

def enregistrer_vote(gagnant, perdant, question_id):
    db = get_db_connection()

    # Vérifier si l'utilisateur a déjà voté
    if db.vote.find_one({
        "id_navigateur": st.session_state.id_navigateur,
        "id_question": question_id
    }):
        st.warning("⚠️ Vous avez déjà voté pour cette question.")
    else:
        # Enregistrer le vote
        db.vote.insert_one({
            "id_navigateur": st.session_state.id_navigateur,
            "id_question": question_id,
            "id_idee_gagnant": gagnant,
            "id_idee_perdant": perdant,
            "date_vote": datetime.now()
        })

        # Mettre à jour les analytics après le vote
        update_sentiment_analytics(question_id)

        st.success("✅ Merci pour votre vote !")

def afficher_formulaire_profil():
    db = get_db_connection()

    if db.profil.find_one({"id_navigateur": st.session_state.id_navigateur}):
        st.success("🎉 Merci ! Vous avez déjà rempli le formulaire.")
        return

    st.subheader("🧾 Veuillez compléter ce court formulaire")
    pays = st.text_input("Pays")
    age = st.number_input("Âge", min_value=10, max_value=120)
    sexe = st.selectbox("Sexe", ["Homme", "Femme", "Autre"])
    fonction = st.text_input("Fonction")

    if st.button("Soumettre"):
        db.profil.insert_one({
            "id_navigateur": st.session_state.id_navigateur,
            "pays": pays,
            "age": age,
            "sexe": sexe,
            "fonction": fonction,
            "date_creation": datetime.now()
        })
        st.success("✅ Profil enregistré avec succès.")

# 🔧 FONCTION VOIR_RESULTATS COMPLÈTEMENT CORRIGÉE
def voir_resultats():
    st.title("📊 Résultats des votes par question")

    db = get_db_connection()

    try:
        # Étape 1: Récupérer toutes les questions avec leurs idées
        questions_avec_idees = list(db.question.aggregate([
            {
                "$lookup": {
                    "from": "idees",
                    "localField": "_id",
                    "foreignField": "id_question",
                    "as": "idees"
                }
            },
            {
                "$match": {
                    "idees": {"$ne": []}  # Seulement les questions qui ont des idées
                }
            }
        ]))

        if not questions_avec_idees:
            st.warning("Aucune question avec des idées trouvée.")
            return

        # Traitement de chaque question
        for question_doc in questions_avec_idees:
            question_id = question_doc["_id"]
            question_text = question_doc["question"]
            idees = question_doc["idees"]

            st.markdown(f"## ❓ {question_text}")

            # Calculer les statistiques de vote pour chaque idée
            data = []
            for idee in idees:
                idee_id = idee["_id"]
                
                # Compter les victoires et défaites
                victoires = db.vote.count_documents({"id_idee_gagnant": idee_id})
                defaites = db.vote.count_documents({"id_idee_perdant": idee_id})
                
                total = victoires + defaites
                score = round((victoires / total) * 100, 2) if total > 0 else 0.0

                # Utiliser .get() pour tous les champs
                type_idee = "Proposée" if idee.get("creer_par_utilisateur", "non") == "oui" else "Initiale"

                data.append({
                    "Idée": idee.get("idee_texte", "Idée sans texte"),
                    "Score": float(score),
                    "Type": type_idee,
                    "Sentiment": idee.get("sentiment_label", "Non analysé"),
                    "Score Sentiment": float(idee.get("sentiment_score", 0.0)),
                    "Victoires": int(victoires),
                    "Défaites": int(defaites),
                    "Total Votes": int(total)
                })

            if not data:
                st.info("Aucune donnée de vote disponible pour cette question.")
                continue

            # Créer le DataFrame et trier
            df = pd.DataFrame(data).sort_values(by="Score", ascending=False)

            # 🏆 Idée la plus soutenue
            if not df.empty:
                meilleure = df.iloc[0]
                st.success(f"🏆 **Idée la plus soutenue :** _{meilleure['Idée']}_ avec un score de **{meilleure['Score']:.1f}%** (Sentiment: {meilleure['Sentiment']})")

            # 📋 Tableau des résultats
            st.markdown("### 📋 Détail des scores avec analyse de sentiment")
            
            # Afficher les colonnes principales
            df_display = df[["Idée", "Score", "Type", "Sentiment", "Victoires", "Défaites", "Total Votes"]]
            st.dataframe(df_display, use_container_width=True)

            # 📊 Visualisation
            st.markdown("### 📊 Graphique des scores")
            if len(df) > 1:
                afficher_comparaison_par_score_et_sentiment(df)

            st.markdown("---")

    except Exception as e:
        st.error(f"❌ Erreur lors de la récupération des résultats : {e}")
        
        # Debug: Afficher des informations sur la structure des données
        st.markdown("### 🔍 Informations de debug")
        
        # Vérifier la structure des collections
        sample_question = db.question.find_one({})
        sample_idee = db.idees.find_one({})
        sample_vote = db.vote.find_one({})
        
        if sample_question:
            st.write("**Structure question:**", list(sample_question.keys()))
        if sample_idee:
            st.write("**Structure idée:**", list(sample_idee.keys()))
        if sample_vote:
            st.write("**Structure vote:**", list(sample_vote.keys()))

def afficher_comparaison_par_score_et_sentiment(df):
    """Graphique comparatif avec scores et sentiments"""
    if df.empty:
        return

    # Graphique principal : Score vs Sentiment
    scatter = alt.Chart(df).mark_circle(size=200, opacity=0.8).encode(
        x=alt.X('Score:Q', title="Score de Vote (%)", scale=alt.Scale(domain=[0, 100])),
        y=alt.Y('Score Sentiment:Q', title="Score de Sentiment", scale=alt.Scale(domain=[-1, 1])),
        color=alt.Color('Type:N', scale=alt.Scale(domain=["Initiale", "Proposée"], range=["#1f77b4", "#ff7f0e"])),
        tooltip=['Idée', 'Score', 'Sentiment', 'Score Sentiment', 'Type']
    ).properties(
        width=600,
        height=400,
        title="Relation Score de Vote vs Sentiment"
    )

    # Lignes de référence
    hline = alt.Chart(pd.DataFrame({'y': [0]})).mark_rule(color='gray', strokeDash=[2, 2]).encode(y='y:Q')
    vline = alt.Chart(pd.DataFrame({'x': [50]})).mark_rule(color='gray', strokeDash=[2, 2]).encode(x='x:Q')

    # Histogramme des sentiments
    hist_sentiment = alt.Chart(df).mark_bar(opacity=0.7).encode(
        x=alt.X('count()', title='Nombre d\'idées'),
        y=alt.Y('Sentiment:N', title='Sentiment'),
        color=alt.Color('Sentiment:N', scale=alt.Scale(domain=['Positif', 'Neutre', 'Négatif'],
                                                      range=['#2ca02c', '#ff7f0e', '#d62728']))
    ).properties(
        width=300,
        height=200,
        title="Distribution des Sentiments"
    )

    # Combiner les graphiques
    combined = alt.hconcat(scatter + hline + vline, hist_sentiment)
    st.altair_chart(combined, use_container_width=True)

# 🔧 FONCTION STATISTIQUES_VOTES CORRIGÉE
def afficher_statistiques_votes():
    """Dashboard des statistiques de votes pour une question sélectionnée"""
    st.title("📊 Statistiques des Votes")

    db = get_db_connection()

    # Récupérer la liste des questions
    questions = list(db.question.find({}, {"_id": 1, "question": 1}).sort("date_creation", -1))

    if not questions:
        st.warning("Aucune question disponible.")
        return

    # Liste déroulante pour sélectionner la question
    question_options = {f"{q['question'][:80]}..." if len(q['question']) > 80 else q['question']: q['_id'] for q in questions}

    selected_question_text = st.selectbox(
        "🔍 Sélectionnez une question à analyser :",
        options=list(question_options.keys()),
        index=0
    )

    selected_question_id = question_options[selected_question_text]

    # Version simplifiée pour éviter les erreurs de pipeline
    try:
        # Récupérer tous les votes pour cette question
        votes = list(db.vote.find({"id_question": selected_question_id}))
        
        if not votes:
            st.warning("Aucune donnée de vote disponible pour cette question.")
            return

        # Récupérer toutes les idées de cette question
        idees = list(db.idees.find({"id_question": selected_question_id}))
        
        # Calculer les statistiques pour chaque idée
        data_votes = []
        for idee in idees:
            idee_id = idee["_id"]
            victoires = sum(1 for vote in votes if vote["id_idee_gagnant"] == idee_id)
            defaites = sum(1 for vote in votes if vote["id_idee_perdant"] == idee_id)
            total = victoires + defaites
            pourcentage = round((victoires / total) * 100, 1) if total > 0 else 0

            # 🔧 CORRECTION : utiliser .get() au lieu d'accès direct
            type_idee = "Proposée par utilisateur" if idee.get("creer_par_utilisateur", "non") == "oui" else "Idée initiale"

            data_votes.append({
                'Idée': idee.get('idee_texte', 'Idée sans texte')[:50] + "..." if len(idee.get('idee_texte', '')) > 50 else idee.get('idee_texte', 'Idée sans texte'),
                'Pourcentage': float(pourcentage),
                'Victoires': victoires,
                'Défaites': defaites,
                'Total': total,
                'Type': type_idee
            })

        # Affichage des métriques principales
        if data_votes:
            col1, col2, col3 = st.columns(3)

            total_votes = sum([d['Total'] for d in data_votes])
            meilleure_idee = max(data_votes, key=lambda x: x['Pourcentage']) if data_votes else None
            nb_idees = len(data_votes)

            with col1:
                st.metric("📊 Total des votes", int(total_votes))
            with col2:
                st.metric("💡 Nombre d'idées", int(nb_idees))
            with col3:
                if meilleure_idee:
                    st.metric("🏆 Meilleur score", f"{float(meilleure_idee['Pourcentage'])}%")

            # Graphique en barres - Pourcentage de victoires
            df_votes = pd.DataFrame(data_votes)

            chart_bars = alt.Chart(df_votes).mark_bar().encode(
                x=alt.X('Pourcentage:Q', title='Pourcentage de victoires (%)', scale=alt.Scale(domain=[0, 100])),
                y=alt.Y('Idée:N', sort='-x', title='Idées'),
                color=alt.Color('Type:N',
                              scale=alt.Scale(domain=["Idée initiale", "Proposée par utilisateur"],
                                            range=["#1f77b4", "#ff7f0e"]),
                              title="Type d'idée"),
                tooltip=['Idée:N', 'Pourcentage:Q', 'Victoires:Q', 'Défaites:Q', 'Type:N']
            ).properties(
                width=700,
                height=400,
                title=f"Pourcentage de victoires par idée"
            )

            st.altair_chart(chart_bars, use_container_width=True)

            # Graphique circulaire - Répartition des votes
            chart_pie = alt.Chart(df_votes).mark_arc(innerRadius=50, outerRadius=120).encode(
                theta=alt.Theta('Victoires:Q', title='Nombre de victoires'),
                color=alt.Color('Idée:N', legend=alt.Legend(orient="right")),
                tooltip=['Idée:N', 'Victoires:Q', 'Pourcentage:Q']
            ).properties(
                width=400,
                height=400,
                title="Répartition des victoires"
            )

            st.altair_chart(chart_pie, use_container_width=True)

            # Tableau détaillé
            st.markdown("### 📋 Détail des résultats")
            st.dataframe(
                df_votes[['Idée', 'Pourcentage', 'Victoires', 'Défaites', 'Total', 'Type']],
                use_container_width=True
            )

    except Exception as e:
        st.error(f"❌ Erreur lors de l'analyse des statistiques : {e}")

def afficher_analyse_sentiment_complete():
    """Dashboard complet d'analyse de sentiment avec option de comparaison"""
    st.title("🧠 Analyse de Sentiment Avancée")

    # Options de visualisation
    tab1, tab2 = st.tabs(["📊 Question Individuelle", "📄 Comparaison Questions"])

    with tab1:
        afficher_sentiment_question_individuelle()

    with tab2:
        afficher_comparaison_sentiment_questions()

def afficher_sentiment_question_individuelle():
    """Analyse de sentiment pour une question individuelle"""
    db = get_db_connection()

    # Récupérer les questions
    questions = list(db.question.find({}, {"_id": 1, "question": 1}).sort("date_creation", -1))

    if not questions:
        st.warning("Aucune question disponible.")
        return

    # Sélection de la question
    question_options = {f"{q['question'][:80]}..." if len(q['question']) > 80 else q['question']: q['_id'] for q in questions}

    selected_question_text = st.selectbox(
        "🔍 Choisissez une question pour l'analyse de sentiment :",
        options=list(question_options.keys()),
        key="sentiment_individual"
    )

    selected_question_id = question_options[selected_question_text]

    # Récupérer toutes les données textuelles pour cette question
    idees = list(db.idees.find({"id_question": selected_question_id}, {
        "idee_texte": 1, "sentiment_score": 1, "sentiment_label": 1, "creer_par_utilisateur": 1
    }))

    commentaires = list(db.commentaire.find({"id_question": selected_question_id}, {
        "commentaire": 1, "sentiment_score": 1, "sentiment_label": 1
    }))

    if not idees and not commentaires:
        st.warning("Aucun contenu textuel disponible pour cette question.")
        return

    # Analyse globale combinée
    tous_textes = " ".join([i.get('idee_texte', '') for i in idees] + [c.get('commentaire', '') for c in commentaires])
    sentiment_global_score, sentiment_global_label = analyze_sentiment(tous_textes)

    # Métriques principales
    col1, col2, col3, col4 = st.columns(4)

    nb_idees = len(idees)
    nb_commentaires = len(commentaires)

    with col1:
        st.metric("💡 Idées", int(nb_idees))
    with col2:
        st.metric("💬 Commentaires", int(nb_commentaires))
    with col3:
        st.metric("🧠 Sentiment Global", sentiment_global_label)
    with col4:
        st.metric("📊 Score Global", f"{float(sentiment_global_score):.3f}")

    # Préparer les données pour visualisation
    sentiment_data = []

    for idee in idees:
        sentiment_data.append({
            'Texte': (idee.get('idee_texte', '')[:100] + "...") if len(idee.get('idee_texte', '')) > 100 else idee.get('idee_texte', ''),
            'Type': 'Idée',
            'Sentiment': idee.get('sentiment_label', 'Non analysé'),
            'Score': float(idee.get('sentiment_score', 0)),
            'Origine': 'Utilisateur' if idee.get('creer_par_utilisateur') == 'oui' else 'Initial'
        })

    for comment in commentaires:
        sentiment_data.append({
            'Texte': (comment.get('commentaire', '')[:100] + "...") if len(comment.get('commentaire', '')) > 100 else comment.get('commentaire', ''),
            'Type': 'Commentaire',
            'Sentiment': comment.get('sentiment_label', 'Non analysé'),
            'Score': float(comment.get('sentiment_score', 0)),
            'Origine': 'Commentaire'
        })

    if not sentiment_data:
        st.warning("Aucune donnée de sentiment disponible.")
        return

    df_sentiment = pd.DataFrame(sentiment_data)

    # Graphiques
    col1, col2 = st.columns(2)

    with col1:
        # Distribution des sentiments
        sentiment_counts = df_sentiment['Sentiment'].value_counts().reset_index()
        sentiment_counts.columns = ['Sentiment', 'Nombre']

        chart_sentiment = alt.Chart(sentiment_counts).mark_arc(innerRadius=40).encode(
            theta=alt.Theta('Nombre:Q'),
            color=alt.Color('Sentiment:N',
                          scale=alt.Scale(domain=['Positif', 'Neutre', 'Négatif'],
                                        range=['#2ca02c', '#ff7f0e', '#d62728'])),
            tooltip=['Sentiment:N', 'Nombre:Q']
        ).properties(
            width=300,
            height=300,
            title="Distribution des Sentiments"
        )

        st.altair_chart(chart_sentiment)

    with col2:
        # Scores par type de contenu
        chart_scores = alt.Chart(df_sentiment).mark_boxplot(extent='min-max').encode(
            x='Type:N',
            y=alt.Y('Score:Q', scale=alt.Scale(domain=[-1, 1]), title='Score de Sentiment'),
            color='Type:N'
        ).properties(
            width=300,
            height=300,
            title="Distribution des Scores par Type"
        )

        st.altair_chart(chart_scores)

    # Tableau détaillé
    st.markdown("### 📋 Analyse détaillée")
    st.dataframe(df_sentiment, use_container_width=True)

def afficher_comparaison_sentiment_questions():
    """Comparaison des sentiments entre toutes les questions"""
    st.markdown("### 📄 Comparaison Multi-Questions")

    db = get_db_connection()

    # Récupérer les analytics de toutes les questions
    data_comparison = list(db.sentiment_analytics.aggregate([
        {"$lookup": {
            "from": "question",
            "localField": "id_question",
            "foreignField": "_id",
            "as": "question"
        }},
        {"$unwind": "$question"},
        {"$project": {
            "id_question": 1,
            "question": "$question.question",
            "moyenne_sentiment_idees": 1,
            "moyenne_sentiment_commentaires": 1,
            "total_positifs": {"$add": ["$total_idees_positives", "$total_commentaires_positifs"]},
            "total_negatifs": {"$add": ["$total_idees_negatives", "$total_commentaires_negatifs"]},
            "total_neutres": {"$add": ["$total_idees_neutres", "$total_commentaires_neutres"]}
        }}
    ]))

    if not data_comparison:
        st.warning("Aucune donnée d'analytics disponible pour la comparaison.")
        return

    # Préparer les données pour visualisation comparative
    comparison_data = []
    for row in data_comparison:
        question_courte = (row['question'][:40] + "...") if len(row['question']) > 40 else row['question']

        # Conversion des valeurs et vérification de NULL
        moyenne_idees = row.get('moyenne_sentiment_idees')
        moyenne_comms = row.get('moyenne_sentiment_commentaires')

        if moyenne_idees is not None:
            comparison_data.append({
                'Question': question_courte,
                'ID': row['id_question'],
                'Score_Sentiment': float(moyenne_idees),
                'Type_Contenu': 'Idées'
            })

        if moyenne_comms is not None:
            comparison_data.append({
                'Question': question_courte,
                'ID': row['id_question'],
                'Score_Sentiment': float(moyenne_comms),
                'Type_Contenu': 'Commentaires'
            })

    if not comparison_data:
        st.warning("Données insuffisantes pour la comparaison.")
        return

    df_comparison = pd.DataFrame(comparison_data)

    # Graphique pour les idées
    df_idees = df_comparison[df_comparison['Type_Contenu'] == 'Idées']
    if not df_idees.empty:
        chart_idees = alt.Chart(df_idees).mark_bar(color='#1f77b4').encode(
            x=alt.X('Question:N', sort='-y', axis=alt.Axis(labelAngle=-45)),
            y=alt.Y('Score_Sentiment:Q', scale=alt.Scale(domain=[-1, 1]), title='Score Sentiment Moyen'),
            tooltip=['Question:N', 'Score_Sentiment:Q']
        ).properties(
            width=600,
            height=300,
            title="Sentiment Moyen des Idées par Question"
        )

        # Ligne de référence
        rule = alt.Chart(pd.DataFrame({'y': [0]})).mark_rule(color='red', strokeDash=[2, 2]).encode(y='y:Q')

        st.altair_chart(chart_idees + rule, use_container_width=True)

    # Graphique pour les commentaires
    df_comms = df_comparison[df_comparison['Type_Contenu'] == 'Commentaires']
    if not df_comms.empty:
        chart_comms = alt.Chart(df_comms).mark_bar(color='#ff7f0e').encode(
            x=alt.X('Question:N', sort='-y', axis=alt.Axis(labelAngle=-45)),
            y=alt.Y('Score_Sentiment:Q', scale=alt.Scale(domain=[-1, 1]), title='Score Sentiment Moyen'),
            tooltip=['Question:N', 'Score_Sentiment:Q']
        ).properties(
            width=600,
            height=300,
            title="Sentiment Moyen des Commentaires par Question"
        )

        # Ligne de référence
        rule = alt.Chart(pd.DataFrame({'y': [0]})).mark_rule(color='red', strokeDash=[2, 2]).encode(y='y:Q')

        st.altair_chart(chart_comms + rule, use_container_width=True)

def display_home_page():
    """Affiche la page d'accueil avec HTML moderne et élégant"""

    # CSS personnalisé pour une interface moderne
    st.markdown("""
    <style>
        /* Import Google Fonts */
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');

        .main-container {
            font-family: 'Inter', sans-serif;
        }

        /* Hero Section */
        .hero-section {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 4rem 2rem;
            border-radius: 20px;
            margin-bottom: 3rem;
            text-align: center;
            position: relative;
            overflow: hidden;
        }

        .hero-content {
            position: relative;
            z-index: 2;
        }

        .hero-title {
            font-size: 3.5rem;
            font-weight: 700;
            margin-bottom: 1rem;
            text-shadow: 2px 2px 4px rgba(0,0,0,0.3);
        }

        /* Features Grid */
        .features-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 2rem;
            margin: 3rem 0;
        }

        .feature-card {
            background: white;
            border-radius: 16px;
            padding: 2rem;
            box-shadow: 0 8px 32px rgba(0,0,0,0.1);
            transition: all 0.3s ease;
        }

        .feature-card:hover {
            transform: translateY(-8px);
            box-shadow: 0 16px 48px rgba(0,0,0,0.15);
        }

        /* Admin Section */
        .admin-section {
            background: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%);
            border-radius: 16px;
            padding: 2rem;
            margin: 2rem 0;
            color: white;
        }

        /* About Section */
        .about-section {
            background: white;
            border-radius: 20px;
            padding: 3rem 2rem;
            margin: 3rem 0;
            box-shadow: 0 8px 32px rgba(0,0,0,0.1);
        }

        .about-title {
            font-size: 2.5rem;
            font-weight: 600;
            color: #2d3748;
            margin-bottom: 2rem;
            text-align: center;
        }
    </style>
    """, unsafe_allow_html=True)

    # Hero Section
    st.markdown("""
    <div class="main-container">
        <div class="hero-section">
            <div class="hero-content">
                <h1 class="hero-title">🗳️ QUE VOULONS NOUS POUR L'AFRIQUE </h1>
                <p style="text-align: justify; font-size: 1.2rem; opacity: 0.9;">
                    Plateforme Citoyenne de Vote qui explore les priorités sociales, politiques et économiques des Africains via une plateforme interactive
                    où les participants peuvent proposer, évaluer, et classer des idées pour l'avenir du continent.
                </p>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # Section d'upload d'image pour l'admin
    if st.session_state.get("auth") and st.session_state.get("email") == "yinnaasome@gmail.com":
        st.markdown("""
        <div class="admin-section">
            <h3>🛠️ Administration - Gestion des Médias</h3>
            <p>En tant qu'administrateur, vous pouvez télécharger des images pour illustrer les objectifs de la plateforme.</p>
        </div>
        """, unsafe_allow_html=True)

        with st.expander("🖼️ Gérer les images de la plateforme", expanded=False):
            uploaded_file = st.file_uploader(
                "Télécharger une image (objectifs de la plateforme)",
                type=["jpg", "png", "jpeg"]
            )

            if uploaded_file is not None:
                try:
                    img = Image.open(uploaded_file)
                    if img.width > 800:
                        img = img.resize((800, int(img.height * 800 / img.width)))
                    st.image(img, caption="Aperçu de l'image téléchargée", use_column_width=True)
                    if st.button("💾 Sauvegarder cette image"):
                        st.success("✅ Image sauvegardée avec succès!")
                except Exception as e:
                    st.error(f"❌ Erreur lors du traitement de l'image: {e}")

    # About Section
    st.markdown("""
    <div class="about-section">
        <h2 class="about-title">🎯 Notre Mission</h2>
        <div>
            <p style="text-align: justify; font-size: 1.2rem;">
                Faciliter un dialogue inclusif et constructif. Créez une plateforme en ligne qui permette à chaque citoyen africain,
                quel que soit son niveau d'éducation ou son lieu de résidence, de partager ses idées pour l'avenir de l'Afrique.
                Rejoignez notre communauté grandissante de citoyens engagés et
                contribuez à façonner un avenir plus démocratique et inclusif.
            </p>
        </div>
    </div>
    """, unsafe_allow_html=True)

# === Fonction principale avec onglets horizontaux ===
def main():
    # Onglets principaux en haut
    onglets_principaux = st.tabs(["🏠 Accueil", "➕ Créer une question", "🗳 Participer au vote", "📈 Voir les Statistiques"])

    # Onglet Accueil
    with onglets_principaux[0]:
        display_home_page()

    # Onglet Créer question
    with onglets_principaux[1]:
        creer_question()

    # Onglet Participer au vote
    with onglets_principaux[2]:
        participer()

    # Onglet Statistiques (avec sous-onglets)
    with onglets_principaux[3]:
        sous_onglets = st.tabs(["🧠 Analyse de Sentiment", "📊 Voir les résultats", "📈 Statistiques des Votes"])

        with sous_onglets[0]:
            afficher_analyse_sentiment_complete()

        with sous_onglets[1]:
            voir_resultats()

        with sous_onglets[2]:
            afficher_statistiques_votes()

# === Point d'entrée ===
if __name__ == "__main__":
    main()