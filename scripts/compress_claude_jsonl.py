#!/usr/bin/env python3
"""Offline Claude Code JSONL compressor.

This tool creates a smaller candidate transcript by replacing early/middle
history with a compact-style summary pair and preserving a recent raw tail.
It is intentionally conservative about schema: unknown fields are kept on
preserved records, and synthetic records use only fields commonly seen in
Claude Code JSONL.
"""

from __future__ import annotations

import argparse
import collections
import copy
import datetime as _dt
import hashlib
import json
import os
import pathlib
import re
import sys
import unicodedata
import uuid
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


JsonObj = Dict[str, Any]
PACKAGE_VERSION = "1.0.0-rc.1"
CODEX_OFFLINE_COMPRESSION_VERSION = "v10"
MODEL_PACK_SCHEMA_VERSION = 11
REPORT_SCHEMA_VERSION = 1
PRIOR_SUMMARY_VERBATIM_BUDGET_FACTOR = 1.5
MIN_SUMMARY_CHAR_BUDGET = 4000
DEFAULT_MODEL_PACK_ESTIMATED_TOKEN_BUDGET = 150000


def configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


configure_stdio()

DEFAULT_IMPORTANCE_WORDS = tuple(
[
    "must",
    "must not",
    "do not",
    "don't",
    "cannot",
    "forbidden",
    "required",
    "need",
    "shall",
    "should",
    "should not",
    "goal",
    "objective",
    "scope",
    "constraint",
    "bottom line",
    "principle",
    "priority",
    "deadline",
    "assumption",
    "decision",
    "final decision",
    "conclusion",
    "approved",
    "rejected",
    "discarded",
    "abandoned",
    "reversed",
    "changed",
    "superseded",
    "reason",
    "rationale",
    "because",
    "why",
    "tradeoff",
    "evidence",
    "source",
    "citation",
    "reference",
    "provenance",
    "verified",
    "official",
    "version",
    "revision",
    "timeline",
    "chronology",
    "before",
    "after",
    "latest",
    "current",
    "previous",
    "risk",
    "issue",
    "bug",
    "error",
    "warning",
    "unknown",
    "open question",
    "unresolved",
    "TODO",
    "blocker",
    "legal",
    "law",
    "compliance",
    "privacy",
    "copyright",
    "license",
    "audit",
    "liability",
    "policy",
    "contract",
    "clause",
    "case law",
    "strategy",
    "plan",
    "milestone",
    "feasibility",
    "research",
    "document",
    "brief",
    "memo",
    "draft",
    "outline",
    "style",
    "tone",
    "audience",
    "file",
    "path",
    "directory",
    "deliverable",
    "summary",
    "preserve",
    "rewind",
    "compact",
    "context",
    "token",
    "jsonl",
    "session",
    "\u5fc5\u987b",
    "\u52a1\u5fc5",
    "\u4e0d\u8981",
    "\u4e0d\u80fd",
    "\u4e0d\u53ef",
    "\u4e0d\u8bb8",
    "\u7981\u6b62",
    "\u9700\u8981",
    "\u5e94\u5f53",
    "\u4e0d\u8981\u5fd8\u8bb0",
    "\u8bf7\u8bb0\u4f4f",
    "\u6ce8\u610f",
    "\u91cd\u70b9",
    "\u5e95\u7ebf",
    "\u539f\u5219",
    "\u7ea6\u675f",
    "\u9650\u5236",
    "\u76ee\u6807",
    "\u8303\u56f4",
    "\u4f18\u5148\u7ea7",
    "\u622a\u6b62",
    "\u5047\u8bbe",
    "\u51b3\u5b9a",
    "\u7ed3\u8bba",
    "\u6700\u7ec8",
    "\u5df2\u5b9a",
    "\u6539\u4e3a",
    "\u53d8\u66f4",
    "\u4fee\u6b63",
    "\u5426\u5b9a",
    "\u653e\u5f03",
    "\u5e9f\u5f03",
    "\u4e0d\u518d",
    "\u53d6\u4ee3",
    "\u539f\u56e0",
    "\u7406\u7531",
    "\u7f18\u7531",
    "\u4f9d\u636e",
    "\u8bc1\u636e",
    "\u6765\u6e90",
    "\u51fa\u5904",
    "\u5f15\u7528",
    "\u5b98\u65b9",
    "\u6838\u67e5",
    "\u9a8c\u8bc1",
    "\u6eaf\u6e90",
    "\u65f6\u95f4\u7ebf",
    "\u5148\u524d",
    "\u540e\u6765",
    "\u5f53\u524d",
    "\u6700\u65b0",
    "\u98ce\u9669",
    "\u95ee\u9898",
    "\u9519\u8bef",
    "\u5f02\u5e38",
    "\u7591\u70b9",
    "\u672a\u77e5",
    "\u5f85\u5b9a",
    "\u672a\u89e3\u51b3",
    "\u963b\u585e",
    "\u6cd5\u5f8b",
    "\u6cd5\u89c4",
    "\u5408\u89c4",
    "\u9690\u79c1",
    "\u7248\u6743",
    "\u8bb8\u53ef",
    "\u5ba1\u8ba1",
    "\u5408\u540c",
    "\u6761\u6b3e",
    "\u5224\u4f8b",
    "\u7b56\u7565",
    "\u8ba1\u5212",
    "\u91cc\u7a0b\u7891",
    "\u53ef\u884c\u6027",
    "\u8c03\u7814",
    "\u7814\u7a76",
    "\u6587\u6863",
    "\u6587\u4e66",
    "\u62a5\u544a",
    "\u5907\u5fd8\u5f55",
    "\u8349\u7a3f",
    "\u5927\u7eb2",
    "\u98ce\u683c",
    "\u8bed\u6c14",
    "\u53d7\u4f17",
    "\u6587\u4ef6",
    "\u8def\u5f84",
    "\u76ee\u5f55",
    "\u4ea4\u4ed8",
    "\u6458\u8981",
    "\u4fdd\u7559",
    "\u538b\u7f29",
    "\u4e0a\u4e0b\u6587",
    "\u4f1a\u8bdd",
    "\u5fc5\u9808",
    "\u52d9\u5fc5",
    "\u61c9\u7576",
    "\u8acb\u8a18\u4f4f",
    "\u91cd\u9ede",
    "\u5e95\u7dda",
    "\u539f\u5247",
    "\u7d04\u675f",
    "\u7bc4\u570d",
    "\u512a\u5148\u7d1a",
    "\u6c7a\u5b9a",
    "\u7d50\u8ad6",
    "\u6700\u7d42",
    "\u8b8a\u66f4",
    "\u5ee2\u68c4",
    "\u4f9d\u64da",
    "\u8b49\u64da",
    "\u4f86\u6e90",
    "\u9a57\u8b49",
    "\u6642\u9593\u7dda",
    "\u98a8\u96aa",
    "\u932f\u8aa4",
    "\u7570\u5e38",
    "\u96b1\u79c1",
    "\u7248\u6b0a",
    "\u5408\u7d04",
    "\u8a08\u756b",
    "\u3057\u3066\u306f\u3044\u3051\u306a\u3044",
    "\u5fc5\u8981",
    "\u76ee\u7684",
    "\u76ee\u6a19",
    "\u5236\u7d04",
    "\u524d\u63d0",
    "\u5909\u66f4",
    "\u5374\u4e0b",
    "\u7834\u68c4",
    "\u6839\u62e0",
    "\u8a3c\u62e0",
    "\u51fa\u5178",
    "\u516c\u5f0f",
    "\u691c\u8a3c",
    "\u6642\u7cfb\u5217",
    "\u4ee5\u524d",
    "\u73fe\u5728",
    "\u30ea\u30b9\u30af",
    "\u8ab2\u984c",
    "\u672a\u89e3\u6c7a",
    "\u6cd5\u4ee4",
    "\u30b3\u30f3\u30d7\u30e9\u30a4\u30a2\u30f3\u30b9",
    "\u8457\u4f5c\u6a29",
    "\u5951\u7d04",
    "\u6761\u9805",
    "\u6226\u7565",
    "\u8a08\u753b",
    "\u5b9f\u73fe\u53ef\u80fd\u6027",
    "\u8abf\u67fb",
    "\u6587\u66f8",
    "\u8349\u6848",
    "\u30b9\u30bf\u30a4\u30eb",
    "\u8981\u7d04",
    "\u4fdd\u5b58",
    "\u5727\u7e2e",
    "\u6587\u8108",
    "\u30bb\u30c3\u30b7\u30e7\u30f3",
    "\ud544\uc218",
    "\uae08\uc9c0",
    "\ud558\uc9c0 \ub9d0 \uac83",
    "\ud544\uc694",
    "\ubaa9\ud45c",
    "\uc81c\uc57d",
    "\uc6d0\uce59",
    "\uacb0\uc815",
    "\uacb0\ub860",
    "\ucd5c\uc885",
    "\ubcc0\uacbd",
    "\uc218\uc815",
    "\uac70\ubd80",
    "\ud3d0\uae30",
    "\uc774\uc720",
    "\uadfc\uac70",
    "\uc99d\uac70",
    "\ucd9c\ucc98",
    "\uc778\uc6a9",
    "\uacf5\uc2dd",
    "\uac80\uc99d",
    "\ud0c0\uc784\ub77c\uc778",
    "\ud604\uc7ac",
    "\ucd5c\uc2e0",
    "\uc704\ud5d8",
    "\ubb38\uc81c",
    "\ubbf8\ud574\uacb0",
    "\ubc95\ub960",
    "\uaddc\uc815",
    "\uc900\uc218",
    "\uac1c\uc778\uc815\ubcf4",
    "\uc800\uc791\uad8c",
    "\uacc4\uc57d",
    "\uc870\ud56d",
    "\uc804\ub7b5",
    "\uacc4\ud68d",
    "\ud0c0\ub2f9\uc131",
    "\uc870\uc0ac",
    "\uc5f0\uad6c",
    "\ubb38\uc11c",
    "\ubcf4\uace0\uc11c",
    "\ucd08\uc548",
    "\uc694\uc57d",
    "\ubcf4\uc874",
    "\uc555\ucd95",
    "\ub9e5\ub77d",
    "\uc138\uc158",
    "debe",
    "no debe",
    "prohibido",
    "necesario",
    "objetivo",
    "restricci\u00f3n",
    "decisi\u00f3n",
    "conclusi\u00f3n",
    "raz\u00f3n",
    "evidencia",
    "fuente",
    "cita",
    "verificado",
    "riesgo",
    "cumplimiento",
    "contrato",
    "estrategia",
    "investigaci\u00f3n",
    "documento",
    "resumen",
    "preservar",
    "comprimir",
    "doit",
    "ne pas",
    "interdit",
    "n\u00e9cessaire",
    "objectif",
    "contrainte",
    "d\u00e9cision",
    "raison",
    "preuve",
    "v\u00e9rifi\u00e9",
    "risque",
    "juridique",
    "conformit\u00e9",
    "contrat",
    "strat\u00e9gie",
    "recherche",
    "r\u00e9sum\u00e9",
    "pr\u00e9server",
    "compresser",
    "muss",
    "darf nicht",
    "verboten",
    "erforderlich",
    "ziel",
    "einschr\u00e4nkung",
    "entscheidung",
    "schlussfolgerung",
    "grund",
    "beweis",
    "quelle",
    "zitat",
    "verifiziert",
    "risiko",
    "rechtlich",
    "vertrag",
    "strategie",
    "forschung",
    "dokument",
    "zusammenfassung",
    "bewahren",
    "komprimieren",
    "deve",
    "n\u00e3o deve",
    "proibido",
    "necess\u00e1rio",
    "restri\u00e7\u00e3o",
    "decis\u00e3o",
    "conclus\u00e3o",
    "raz\u00e3o",
    "evid\u00eancia",
    "fonte",
    "cita\u00e7\u00e3o",
    "risco",
    "jur\u00eddico",
    "conformidade",
    "estrat\u00e9gia",
    "pesquisa",
    "resumo",
    "compactar",
    "brand",
    "branding",
    "brand strategy",
    "brand management",
    "brand governance",
    "brand architecture",
    "brand system",
    "brand platform",
    "brand positioning",
    "positioning",
    "value proposition",
    "messaging",
    "narrative",
    "tagline",
    "slogan",
    "campaign",
    "marketing",
    "market research",
    "competitive analysis",
    "persona",
    "customer journey",
    "touchpoint",
    "channel",
    "content strategy",
    "digital management",
    "asset management",
    "DAM",
    "design system",
    "visual identity",
    "identity system",
    "logo",
    "logotype",
    "typography",
    "color palette",
    "layout",
    "grid",
    "component",
    "guideline",
    "style guide",
    "brand book",
    "tone of voice",
    "voice and tone",
    "creative direction",
    "art direction",
    "concept",
    "moodboard",
    "prototype",
    "wireframe",
    "UI",
    "UX",
    "service design",
    "experience design",
    "information architecture",
    "usability",
    "accessibility",
    "brand audit",
    "brand equity",
    "brand consistency",
    "brand compliance",
    "approval workflow",
    "rights management",
    "localization",
    "internationalization",
    "\u54c1\u724c",
    "\u54c1\u724c\u7b56\u7565",
    "\u54c1\u724c\u7ba1\u7406",
    "\u54c1\u724c\u6cbb\u7406",
    "\u54c1\u724c\u67b6\u6784",
    "\u54c1\u724c\u4f53\u7cfb",
    "\u54c1\u724c\u5e73\u53f0",
    "\u54c1\u724c\u5b9a\u4f4d",
    "\u4ef7\u503c\u4e3b\u5f20",
    "\u4f20\u64ad\u53e3\u5f84",
    "\u53d9\u4e8b",
    "\u6807\u8bed",
    "\u53e3\u53f7",
    "\u6d3b\u52a8",
    "\u8425\u9500",
    "\u5e02\u573a\u8c03\u7814",
    "\u7ade\u54c1\u5206\u6790",
    "\u7528\u6237\u753b\u50cf",
    "\u5ba2\u6237\u65c5\u7a0b",
    "\u89e6\u70b9",
    "\u6e20\u9053",
    "\u5185\u5bb9\u7b56\u7565",
    "\u6570\u5b57\u5316\u7ba1\u7406",
    "\u8d44\u4ea7\u7ba1\u7406",
    "\u8bbe\u8ba1\u7cfb\u7edf",
    "\u89c6\u89c9\u8bc6\u522b",
    "\u8bc6\u522b\u7cfb\u7edf",
    "\u6807\u5fd7",
    "\u5b57\u4f53",
    "\u8272\u5f69",
    "\u914d\u8272",
    "\u7248\u5f0f",
    "\u7f51\u683c",
    "\u7ec4\u4ef6",
    "\u89c4\u8303",
    "\u98ce\u683c\u6307\u5357",
    "\u54c1\u724c\u624b\u518c",
    "\u58f0\u97f3\u8bed\u8c03",
    "\u521b\u610f\u65b9\u5411",
    "\u827a\u672f\u6307\u5bfc",
    "\u6982\u5ff5",
    "\u60c5\u7eea\u677f",
    "\u539f\u578b",
    "\u7ebf\u6846\u56fe",
    "\u7528\u6237\u4f53\u9a8c",
    "\u670d\u52a1\u8bbe\u8ba1",
    "\u4f53\u9a8c\u8bbe\u8ba1",
    "\u4fe1\u606f\u67b6\u6784",
    "\u53ef\u7528\u6027",
    "\u65e0\u969c\u788d",
    "\u54c1\u724c\u5ba1\u8ba1",
    "\u54c1\u724c\u8d44\u4ea7",
    "\u54c1\u724c\u4e00\u81f4\u6027",
    "\u54c1\u724c\u5408\u89c4",
    "\u5ba1\u6279\u6d41\u7a0b",
    "\u6743\u5229\u7ba1\u7406",
    "\u672c\u5730\u5316",
    "\u56fd\u9645\u5316",
    "\u30d6\u30e9\u30f3\u30c9",
    "\u30d6\u30e9\u30f3\u30c9\u6226\u7565",
    "\u30d6\u30e9\u30f3\u30c9\u7ba1\u7406",
    "\u30d6\u30e9\u30f3\u30c9\u30ac\u30d0\u30ca\u30f3\u30b9",
    "\u30d6\u30e9\u30f3\u30c9\u30a2\u30fc\u30ad\u30c6\u30af\u30c1\u30e3",
    "\u30dd\u30b8\u30b7\u30e7\u30cb\u30f3\u30b0",
    "\u30e1\u30c3\u30bb\u30fc\u30b8",
    "\u30ca\u30e9\u30c6\u30a3\u30d6",
    "\u30ad\u30e3\u30f3\u30da\u30fc\u30f3",
    "\u5e02\u5834\u8abf\u67fb",
    "\u7af6\u5408\u5206\u6790",
    "\u30aa\u30fc\u30c7\u30a3\u30a8\u30f3\u30b9",
    "\u30da\u30eb\u30bd\u30ca",
    "\u30ab\u30b9\u30bf\u30de\u30fc\u30b8\u30e3\u30fc\u30cb\u30fc",
    "\u30bf\u30c3\u30c1\u30dd\u30a4\u30f3\u30c8",
    "\u30c7\u30b6\u30a4\u30f3\u30b7\u30b9\u30c6\u30e0",
    "\u30d3\u30b8\u30e5\u30a2\u30eb\u30a2\u30a4\u30c7\u30f3\u30c6\u30a3\u30c6\u30a3",
    "\u30ed\u30b4",
    "\u30bf\u30a4\u30dd\u30b0\u30e9\u30d5\u30a3",
    "\u30ab\u30e9\u30fc\u30d1\u30ec\u30c3\u30c8",
    "\u30ac\u30a4\u30c9\u30e9\u30a4\u30f3",
    "\u30d6\u30e9\u30f3\u30c9\u30d6\u30c3\u30af",
    "\u30c8\u30fc\u30f3\u30aa\u30d6\u30dc\u30a4\u30b9",
    "\u30a2\u30fc\u30c8\u30c7\u30a3\u30ec\u30af\u30b7\u30e7\u30f3",
    "\u30d7\u30ed\u30c8\u30bf\u30a4\u30d7",
    "\u30ef\u30a4\u30e4\u30fc\u30d5\u30ec\u30fc\u30e0",
    "\u30e6\u30fc\u30b6\u30fc\u4f53\u9a13",
    "\u30a2\u30af\u30bb\u30b7\u30d3\u30ea\u30c6\u30a3",
    "\ube0c\ub79c\ub4dc",
    "\ube0c\ub79c\ub4dc \uc804\ub7b5",
    "\ube0c\ub79c\ub4dc \uad00\ub9ac",
    "\ube0c\ub79c\ub4dc \uac70\ubc84\ub10c\uc2a4",
    "\ud3ec\uc9c0\uc154\ub2dd",
    "\uba54\uc2dc\uc9d5",
    "\ub0b4\ub7ec\ud2f0\ube0c",
    "\ucea0\ud398\uc778",
    "\uc2dc\uc7a5 \uc870\uc0ac",
    "\uacbd\uc7c1 \ubd84\uc11d",
    "\uc624\ub514\uc5b8\uc2a4",
    "\ud398\ub974\uc18c\ub098",
    "\uace0\uac1d \uc5ec\uc815",
    "\ud130\uce58\ud3ec\uc778\ud2b8",
    "\ub514\uc790\uc778 \uc2dc\uc2a4\ud15c",
    "\ube44\uc8fc\uc5bc \uc544\uc774\ub374\ud2f0\ud2f0",
    "\ub85c\uace0",
    "\ud0c0\uc774\ud3ec\uadf8\ub798\ud53c",
    "\uceec\ub7ec \ud314\ub808\ud2b8",
    "\uac00\uc774\ub4dc\ub77c\uc778",
    "\ube0c\ub79c\ub4dc\ubd81",
    "\ud1a4\uc564\ub9e4\ub108",
    "\ud504\ub85c\ud1a0\ud0c0\uc785",
    "\uc640\uc774\uc5b4\ud504\ub808\uc784",
    "\uc0ac\uc6a9\uc790 \uacbd\ud5d8",
    "\uc811\uadfc\uc131",
    "marca",
    "estrategia de marca",
    "gesti\u00f3n de marca",
    "gobernanza de marca",
    "posicionamiento",
    "propuesta de valor",
    "mensaje",
    "narrativa",
    "campa\u00f1a",
    "investigaci\u00f3n de mercado",
    "an\u00e1lisis competitivo",
    "audiencia",
    "viaje del cliente",
    "punto de contacto",
    "sistema de dise\u00f1o",
    "identidad visual",
    "logotipo",
    "tipograf\u00eda",
    "paleta de colores",
    "gu\u00eda de estilo",
    "marque",
    "strat\u00e9gie de marque",
    "gestion de marque",
    "gouvernance de marque",
    "positionnement",
    "proposition de valeur",
    "r\u00e9cit",
    "campagne",
    "\u00e9tude de march\u00e9",
    "analyse concurrentielle",
    "public cible",
    "parcours client",
    "point de contact",
    "syst\u00e8me de design",
    "identit\u00e9 visuelle",
    "typographie",
    "palette de couleurs",
    "charte graphique",
    "marke",
    "markenstrategie",
    "markenmanagement",
    "markenf\u00fchrung",
    "positionierung",
    "wertversprechen",
    "botschaft",
    "narrativ",
    "kampagne",
    "marktforschung",
    "wettbewerbsanalyse",
    "zielgruppe",
    "designsystem",
    "visuelle identit\u00e4t",
    "typografie",
    "farbpalette",
    "styleguide",
    "estrat\u00e9gia de marca",
    "gest\u00e3o de marca",
    "governan\u00e7a de marca",
    "posicionamento",
    "proposta de valor",
    "mensagem",
    "campanha",
    "pesquisa de mercado",
    "an\u00e1lise competitiva",
    "p\u00fablico",
    "jornada do cliente",
    "ponto de contato",
    "sistema de design",
    "identidade visual",
    "tipografia",
    "paleta de cores",
    "guia de estilo",
    "code",
    "programming",
    "software",
    "engineering",
    "architecture",
    "frontend",
    "backend",
    "full stack",
    "API",
    "SDK",
    "CLI",
    "database",
    "schema",
    "migration",
    "query",
    "cache",
    "queue",
    "worker",
    "service",
    "microservice",
    "monolith",
    "repository",
    "branch",
    "commit",
    "diff",
    "patch",
    "merge",
    "rebase",
    "rollback",
    "release",
    "deployment",
    "build",
    "CI",
    "CD",
    "pipeline",
    "test",
    "unit test",
    "integration test",
    "e2e",
    "fixture",
    "mock",
    "lint",
    "format",
    "type check",
    "debug",
    "trace",
    "log",
    "exception",
    "stack trace",
    "performance",
    "latency",
    "throughput",
    "memory",
    "CPU",
    "security",
    "authentication",
    "authorization",
    "permission",
    "encryption",
    "secret",
    "config",
    "environment",
    "dependency",
    "package",
    "module",
    "function",
    "class",
    "interface",
    "state",
    "hook",
    "render",
    "route",
    "middleware",
    "endpoint",
    "request",
    "response",
    "payload",
    "validation",
    "serialization",
    "JSON",
    "YAML",
    "Docker",
    "container",
    "Kubernetes",
    "cloud",
    "server",
    "client",
    "browser",
    "Node",
    "Python",
    "TypeScript",
    "React",
    "Next.js",
    "Vue",
    "Svelte",
    "\u4ee3\u7801",
    "\u7f16\u7a0b",
    "\u8f6f\u4ef6",
    "\u5de5\u7a0b",
    "\u67b6\u6784",
    "\u524d\u7aef",
    "\u540e\u7aef",
    "\u5168\u6808",
    "\u63a5\u53e3",
    "\u6570\u636e\u5e93",
    "\u6a21\u5f0f",
    "\u8fc1\u79fb",
    "\u67e5\u8be2",
    "\u7f13\u5b58",
    "\u961f\u5217",
    "\u670d\u52a1",
    "\u5fae\u670d\u52a1",
    "\u4ed3\u5e93",
    "\u5206\u652f",
    "\u63d0\u4ea4",
    "\u5dee\u5f02",
    "\u8865\u4e01",
    "\u5408\u5e76",
    "\u56de\u6eda",
    "\u53d1\u5e03",
    "\u90e8\u7f72",
    "\u6784\u5efa",
    "\u6d41\u6c34\u7ebf",
    "\u6d4b\u8bd5",
    "\u5355\u5143\u6d4b\u8bd5",
    "\u96c6\u6210\u6d4b\u8bd5",
    "\u7aef\u5230\u7aef",
    "\u5939\u5177",
    "\u6a21\u62df",
    "\u683c\u5f0f\u5316",
    "\u7c7b\u578b\u68c0\u67e5",
    "\u8c03\u8bd5",
    "\u8ddf\u8e2a",
    "\u65e5\u5fd7",
    "\u5806\u6808",
    "\u6027\u80fd",
    "\u5ef6\u8fdf",
    "\u541e\u5410",
    "\u5185\u5b58",
    "\u5b89\u5168",
    "\u8ba4\u8bc1",
    "\u6388\u6743",
    "\u6743\u9650",
    "\u52a0\u5bc6",
    "\u5bc6\u94a5",
    "\u914d\u7f6e",
    "\u73af\u5883",
    "\u4f9d\u8d56",
    "\u5305",
    "\u6a21\u5757",
    "\u51fd\u6570",
    "\u7c7b",
    "\u72b6\u6001",
    "\u6e32\u67d3",
    "\u8def\u7531",
    "\u4e2d\u95f4\u4ef6",
    "\u7aef\u70b9",
    "\u8bf7\u6c42",
    "\u54cd\u5e94",
    "\u8f7d\u8377",
    "\u6821\u9a8c",
    "\u5e8f\u5217\u5316",
    "\u5bb9\u5668",
    "\u4e91",
    "\u670d\u52a1\u5668",
    "\u5ba2\u6237\u7aef",
    "\u6d4f\u89c8\u5668",
    "\u30b3\u30fc\u30c9",
    "\u30d7\u30ed\u30b0\u30e9\u30df\u30f3\u30b0",
    "\u30bd\u30d5\u30c8\u30a6\u30a7\u30a2",
    "\u30a8\u30f3\u30b8\u30cb\u30a2\u30ea\u30f3\u30b0",
    "\u30a2\u30fc\u30ad\u30c6\u30af\u30c1\u30e3",
    "\u30d5\u30ed\u30f3\u30c8\u30a8\u30f3\u30c9",
    "\u30d0\u30c3\u30af\u30a8\u30f3\u30c9",
    "\u30c7\u30fc\u30bf\u30d9\u30fc\u30b9",
    "\u30b9\u30ad\u30fc\u30de",
    "\u30de\u30a4\u30b0\u30ec\u30fc\u30b7\u30e7\u30f3",
    "\u30ad\u30e3\u30c3\u30b7\u30e5",
    "\u30c6\u30b9\u30c8",
    "\u30c7\u30d0\u30c3\u30b0",
    "\u30ed\u30b0",
    "\u4f8b\u5916",
    "\u30bb\u30ad\u30e5\u30ea\u30c6\u30a3",
    "\u8a8d\u8a3c",
    "\u8a8d\u53ef",
    "\u6a29\u9650",
    "\u8a2d\u5b9a",
    "\u4f9d\u5b58\u95a2\u4fc2",
    "\u30e2\u30b8\u30e5\u30fc\u30eb",
    "\u95a2\u6570",
    "\u30af\u30e9\u30b9",
    "\u30b3\u30f3\u30dd\u30fc\u30cd\u30f3\u30c8",
    "\u30eb\u30fc\u30c6\u30a3\u30f3\u30b0",
    "\u30df\u30c9\u30eb\u30a6\u30a7\u30a2",
    "\u30ea\u30af\u30a8\u30b9\u30c8",
    "\u30ec\u30b9\u30dd\u30f3\u30b9",
    "\u30b7\u30ea\u30a2\u30e9\u30a4\u30ba",
    "\ucf54\ub4dc",
    "\ud504\ub85c\uadf8\ub798\ubc0d",
    "\uc18c\ud504\ud2b8\uc6e8\uc5b4",
    "\uc5d4\uc9c0\ub2c8\uc5b4\ub9c1",
    "\uc544\ud0a4\ud14d\ucc98",
    "\ud504\ub860\ud2b8\uc5d4\ub4dc",
    "\ubc31\uc5d4\ub4dc",
    "\ub370\uc774\ud130\ubca0\uc774\uc2a4",
    "\uc2a4\ud0a4\ub9c8",
    "\ub9c8\uc774\uadf8\ub808\uc774\uc158",
    "\uce90\uc2dc",
    "\ud14c\uc2a4\ud2b8",
    "\ub514\ubc84\uadf8",
    "\ub85c\uadf8",
    "\uc608\uc678",
    "\uc131\ub2a5",
    "\ubcf4\uc548",
    "\uc778\uc99d",
    "\uc778\uac00",
    "\uad8c\ud55c",
    "\uc124\uc815",
    "\uc758\uc874\uc131",
    "\ubaa8\ub4c8",
    "\ud568\uc218",
    "\ud074\ub798\uc2a4",
    "\ucef4\ud3ec\ub10c\ud2b8",
    "\ub77c\uc6b0\ud305",
    "\ubbf8\ub4e4\uc6e8\uc5b4",
    "\uc694\uccad",
    "\uc751\ub2f5",
    "\uc9c1\ub82c\ud654"
]
)

IMPORTANT_WORDS = DEFAULT_IMPORTANCE_WORDS

ASSISTANT_RESEARCH_DECISION_WORDS = (
    "decision",
    "final decision",
    "conclusion",
    "verdict",
    "judgment",
    "rationale",
    "reason",
    "because",
    "therefore",
    "so",
    "tradeoff",
    "trade-off",
    "key insight",
    "critical finding",
    "architectural lesson",
    "better fit",
    "reject",
    "rejected",
    "adopt",
    "adopted",
    "superseded",
    "not use",
    "do not use",
    "verify",
    "verified",
    "validate",
    "validated",
    "official",
    "source",
    "evidence",
    "choice",
    "chosen",
    "not chosen",
    "compare",
    "comparison",
    "weigh",
    "weighed",
    "prefer",
    "preferred",
    "recommend",
    "recommended",
    "\u51b3\u5b9a",
    "\u7ed3\u8bba",
    "\u5224\u65ad",
    "\u88c1\u65ad",
    "\u7406\u7531",
    "\u539f\u56e0",
    "\u56e0\u4e3a",
    "\u6240\u4ee5",
    "\u56e0\u6b64",
    "\u53d6\u820d",
    "\u6743\u8861",
    "\u5173\u952e\u6d1e\u5bdf",
    "\u5173\u952e\u53d1\u73b0",
    "\u91cd\u8981\u53d1\u73b0",
    "\u6280\u672f\u8def\u7ebf",
    "\u67b6\u6784",
    "\u91c7\u7eb3",
    "\u4e0d\u91c7\u7eb3",
    "\u62d2\u7edd",
    "\u5426\u5b9a",
    "\u653e\u5f03",
    "\u53d6\u4ee3",
    "\u4fee\u6b63",
    "\u6539\u4e3a",
    "\u9a8c\u8bc1",
    "\u6838\u5bf9",
    "\u67e5\u8bc1",
    "\u590d\u67e5",
    "\u5b98\u65b9",
    "\u4f9d\u636e",
    "\u8bc1\u636e",
    "\u6c7a\u5b9a",
    "\u7d50\u8ad6",
    "\u7406\u7531",
    "\u539f\u56e0",
    "\u56e0\u70ba",
    "\u56e0\u6b64",
    "\u53d6\u6368",
    "\u6b0a\u8861",
    "\u63a1\u7d0d",
    "\u5426\u5b9a",
    "\u653e\u68c4",
    "\u4fee\u6b63",
    "\u9a57\u8b49",
    "\u4f9d\u64da",
    "\u8b49\u64da",
    "\u5224\u65ad",
    "\u7d50\u8ad6",
    "\u7406\u7531",
    "\u306a\u305c\u306a\u3089",
    "\u3057\u305f\u304c\u3063\u3066",
    "\u305d\u306e\u305f\u3081",
    "\u30c8\u30ec\u30fc\u30c9\u30aa\u30d5",
    "\u63a1\u7528",
    "\u4e0d\u63a1\u7528",
    "\u5374\u4e0b",
    "\u68c4\u5374",
    "\u4fee\u6b63",
    "\u691c\u8a3c",
    "\u6839\u62e0",
    "\u8a3c\u62e0",
    "\uacb0\uc815",
    "\uacb0\ub860",
    "\ud310\ub2e8",
    "\uc774\uc720",
    "\uc65c\ub0d0\ud558\uba74",
    "\ub530\ub77c\uc11c",
    "\uadf8\ub7ec\ubbc0\ub85c",
    "\uad8c\ud615",
    "\uc120\ud0dd",
    "\ucc44\ud0dd",
    "\uac70\ubd80",
    "\ud3d0\uae30",
    "\uc218\uc815",
    "\uac80\uc99d",
    "\uadfc\uac70",
    "\uc99d\uac70",
    "decisión",
    "conclusión",
    "juicio",
    "razón",
    "porque",
    "por lo tanto",
    "compensación",
    "preferir",
    "recomendar",
    "rechazar",
    "adoptar",
    "verificar",
    "evidencia",
    "décision",
    "conclusion",
    "jugement",
    "raison",
    "parce que",
    "donc",
    "compromis",
    "préférer",
    "recommander",
    "rejeter",
    "adopter",
    "vérifier",
    "preuve",
    "entscheidung",
    "schlussfolgerung",
    "urteil",
    "grund",
    "weil",
    "daher",
    "abwägung",
    "bevorzugen",
    "empfehlen",
    "ablehnen",
    "übernehmen",
    "prüfen",
    "beweis",
    "decisão",
    "conclusão",
    "julgamento",
    "razão",
    "porque",
    "portanto",
    "preferir",
    "recomendar",
    "rejeitar",
    "adotar",
    "verificar",
    "evidência",
)

ASSISTANT_RESEARCH_ACTION_WORDS = (
    "i will",
    "i'll",
    "let me",
    "i need to",
    "i have enough",
    "i now have",
    "i'm going to",
    "i will now",
    "now add",
    "now write",
    "now fix",
    "now verify",
    "apply the fix",
    "i'll verify",
    "i'll check",
    "i'll add",
    "i'll write",
    "i'll fix",
    "\u6211\u4f1a",
    "\u6211\u8981",
    "\u6211\u73b0\u5728",
    "\u6211\u6765",
    "\u8ba9\u6211",
    "\u73b0\u5728\u52a0",
    "\u73b0\u5728\u5199",
    "\u73b0\u5728\u4fee",
    "\u73b0\u5728\u9a8c\u8bc1",
    "\u7ee7\u7eed\u67e5",
    "\u6211\u6703",
    "\u6211\u8981",
    "\u8b93\u6211",
    "\u73fe\u5728\u52a0",
    "\u73fe\u5728\u5beb",
    "\u73fe\u5728\u4fee",
    "\u73fe\u5728\u9a57\u8b49",
    "\u7d9a\u7e8c\u67e5",
    "\u79c1\u306f",
    "\u78ba\u8a8d\u3057\u307e\u3059",
    "\u691c\u8a3c\u3057\u307e\u3059",
    "\u8ffd\u52a0\u3057\u307e\u3059",
    "\u4fee\u6b63\u3057\u307e\u3059",
    "\uc81c\uac00",
    "\ud655\uc778\ud558\uaca0\uc2b5\ub2c8\ub2e4",
    "\uac80\uc99d\ud558\uaca0\uc2b5\ub2c8\ub2e4",
    "\ucd94\uac00\ud558\uaca0\uc2b5\ub2c8\ub2e4",
    "\uc218\uc815\ud558\uaca0\uc2b5\ub2c8\ub2e4",
    "voy a",
    "je vais",
    "ich werde",
    "vou",
)

ASSISTANT_HIGH_VALUE_DECISION_WORDS = (
    "final decision",
    "conclusion",
    "verdict",
    "key insight",
    "critical finding",
    "architectural lesson",
    "superseded",
    "rejected",
    "validated",
    "\u7ed3\u8bba",
    "\u6700\u7ec8",
    "\u88c1\u65ad",
    "\u5173\u952e\u53d1\u73b0",
    "\u5173\u952e\u6d1e\u5bdf",
    "\u6280\u672f\u8def\u7ebf",
    "\u53d6\u4ee3",
    "\u5426\u5b9a",
    "\u9a8c\u8bc1",
    "\u7d50\u8ad6",
    "\u6700\u7d42",
    "\u95dc\u9375\u767c\u73fe",
    "\u53d6\u4ee3",
    "\u5426\u5b9a",
    "\u9a57\u8b49",
    "\u7d50\u8ad6",
    "\u5374\u4e0b",
    "\u4e0d\u63a1\u7528",
    "\u691c\u8a3c",
    "\uacb0\ub860",
    "\ucd5c\uc885",
    "\uac70\ubd80",
    "\ud3d0\uae30",
    "\uac80\uc99d",
    "decisión final",
    "conclusión",
    "décision finale",
    "entscheidung",
    "schlussfolgerung",
    "decisão final",
    "conclusão",
)

ASSISTANT_DECISION_LANGUAGE_TERMS: Dict[str, Tuple[str, ...]] = {
    "zh": ("决定", "结论", "判断", "理由", "因为", "因此", "采纳", "否定", "证据", "取代"),
    "ja": ("決定", "結論", "判断", "理由", "なぜなら", "したがって", "採用", "却下", "証拠", "検証"),
    "ko": ("결정", "결론", "판단", "이유", "왜냐하면", "따라서", "채택", "거부", "증거", "검증"),
    "ar": ("قرار", "النتيجة", "الخلاصة", "السبب", "لأن", "لذلك", "اعتماد", "رفض", "دليل", "تحقق", "بديل"),
    "ru": ("решение", "вывод", "причина", "потому что", "поэтому", "принят", "отклон", "доказательств", "провер", "альтернатив"),
    "hi": ("निर्णय", "निष्कर्ष", "कारण", "क्योंकि", "इसलिए", "अपनाया", "अस्वीकार", "प्रमाण", "सत्यापित", "विकल्प"),
    "es": ("decisión", "conclusión", "razón", "porque", "por lo tanto", "adoptar", "rechazar", "evidencia", "verificar"),
    "fr": ("décision", "conclusion", "raison", "parce que", "donc", "adopter", "rejeter", "preuve", "vérifier"),
    "de": ("entscheidung", "schlussfolgerung", "grund", "weil", "daher", "übernehmen", "ablehnen", "beweis", "prüfen"),
    "pt": ("decisão", "conclusão", "razão", "porque", "portanto", "adotar", "rejeitar", "evidência", "verificar"),
    "en": ("decision", "conclusion", "reason", "because", "therefore", "adopt", "reject", "evidence", "verify", "superseded"),
}

PATH_RE = re.compile(
    r"(?:(?:[A-Za-z]:\\\\|[A-Za-z]:/|/)[^\s\"'<>|]{2,}|[\w.\-\u4e00-\u9fff]+\.(?:md|jsonl|json|txt|py|js|ts|tsx|jsx|html|css|csv|yaml|yml|toml|docx|pdf))"
)

DEFAULT_TOPIC_MEMORY_PATTERNS = tuple((name, tuple(needles)) for name, needles in
[
    [
        "User goals and hard constraints",
        [
            "goal",
            "objective",
            "scope",
            "constraint",
            "bottom line",
            "must",
            "must not",
            "do not",
            "required",
            "deadline",
            "\u76ee\u6807",
            "\u8303\u56f4",
            "\u5fc5\u987b",
            "\u52a1\u5fc5",
            "\u5e95\u7ebf",
            "\u9650\u5236",
            "\u4e0d\u8981",
            "\u4e0d\u80fd",
            "\u7981\u6b62",
            "\u5fc5\u8981",
            "\u76ee\u7684",
            "\u76ee\u6a19",
            "\u5236\u7d04",
            "\ud544\uc218",
            "\ubaa9\ud45c",
            "\uc81c\uc57d",
            "objetivo",
            "restricci\u00f3n",
            "objectif",
            "contrainte",
            "ziel",
            "einschr\u00e4nkung",
            "restri\u00e7\u00e3o"
        ]
    ],
    [
        "Decisions, reversals, and version changes",
        [
            "decision",
            "final decision",
            "conclusion",
            "approved",
            "rejected",
            "discarded",
            "abandoned",
            "reversed",
            "changed",
            "superseded",
            "version",
            "revision",
            "\u51b3\u5b9a",
            "\u7ed3\u8bba",
            "\u6700\u7ec8",
            "\u5df2\u5b9a",
            "\u6539\u4e3a",
            "\u53d8\u66f4",
            "\u4fee\u6b63",
            "\u5426\u5b9a",
            "\u653e\u5f03",
            "\u5e9f\u5f03",
            "\u53d6\u4ee3",
            "\u6c7a\u5b9a",
            "\u6700\u7d42",
            "\u5909\u66f4",
            "\u5374\u4e0b",
            "\u7834\u68c4",
            "\uacb0\uc815",
            "\uacb0\ub860",
            "\ucd5c\uc885",
            "\ubcc0\uacbd",
            "\uac70\ubd80",
            "\ud3d0\uae30",
            "decisi\u00f3n",
            "conclusi\u00f3n",
            "d\u00e9cision",
            "entscheidung",
            "schlussfolgerung",
            "decis\u00e3o",
            "conclus\u00e3o"
        ]
    ],
    [
        "Evidence and provenance",
        [
            "evidence",
            "source",
            "citation",
            "reference",
            "provenance",
            "verified",
            "official",
            "research",
            "audit",
            "\u8bc1\u636e",
            "\u6765\u6e90",
            "\u51fa\u5904",
            "\u5f15\u7528",
            "\u5b98\u65b9",
            "\u6838\u67e5",
            "\u9a8c\u8bc1",
            "\u6eaf\u6e90",
            "\u8c03\u7814",
            "\u8a3c\u62e0",
            "\u51fa\u5178",
            "\u516c\u5f0f",
            "\u691c\u8a3c",
            "\u6839\u62e0",
            "\uc99d\uac70",
            "\ucd9c\ucc98",
            "\uc778\uc6a9",
            "\uacf5\uc2dd",
            "\uac80\uc99d",
            "evidencia",
            "fuente",
            "cita",
            "preuve",
            "beweis",
            "quelle",
            "zitat",
            "evid\u00eancia",
            "fonte",
            "cita\u00e7\u00e3o"
        ]
    ],
    [
        "Timeline and chronology",
        [
            "timeline",
            "chronology",
            "before",
            "after",
            "previous",
            "current",
            "latest",
            "now",
            "then",
            "\u65f6\u95f4\u7ebf",
            "\u5148\u524d",
            "\u540e\u6765",
            "\u5f53\u524d",
            "\u6700\u65b0",
            "\u4e4b\u524d",
            "\u4e4b\u540e",
            "\u6642\u7cfb\u5217",
            "\u4ee5\u524d",
            "\u73fe\u5728",
            "\ud0c0\uc784\ub77c\uc778",
            "\uc774\uc804",
            "\ud604\uc7ac",
            "\ucd5c\uc2e0",
            "cronolog\u00eda",
            "antes",
            "despu\u00e9s",
            "actuel",
            "chronologie",
            "vorher",
            "nachher",
            "zeitachse",
            "linha do tempo"
        ]
    ],
    [
        "Files, directories, and deliverables",
        [
            "file",
            "directory",
            "path",
            "deliverable",
            "document",
            "brief",
            "memo",
            "draft",
            "outline",
            "report",
            "brand book",
            "style guide",
            "guideline",
            "design system",
            "prototype",
            "wireframe",
            ".md",
            ".jsonl",
            ".json",
            ".py",
            "\u6587\u4ef6",
            "\u76ee\u5f55",
            "\u8def\u5f84",
            "\u4ea4\u4ed8",
            "\u6587\u6863",
            "\u6587\u4e66",
            "\u62a5\u544a",
            "\u8349\u7a3f",
            "\u5927\u7eb2",
            "\u54c1\u724c\u624b\u518c",
            "\u98ce\u683c\u6307\u5357",
            "\u8bbe\u8ba1\u7cfb\u7edf",
            "\u539f\u578b",
            "\u7ebf\u6846\u56fe",
            "\u6587\u66f8",
            "\u5831\u544a",
            "\u8349\u6848",
            "\ubb38\uc11c",
            "\ubcf4\uace0\uc11c",
            "\ucd08\uc548",
            "archivo",
            "documento",
            "informe",
            "borrador",
            "fichier",
            "rapport",
            "brouillon",
            "datei",
            "dokument",
            "bericht",
            "entwurf",
            "arquivo",
            "relat\u00f3rio",
            "rascunho"
        ]
    ],
    [
        "Tools, APIs, and runtime",
        [
            "tool",
            "runtime",
            "session",
            "api",
            "cli",
            "jsonl",
            "token",
            "context",
            "database",
            "script",
            "model",
            "code",
            "programming",
            "software",
            "engineering",
            "architecture",
            "frontend",
            "backend",
            "API",
            "SDK",
            "schema",
            "migration",
            "cache",
            "repository",
            "commit",
            "deployment",
            "test",
            "debug",
            "security",
            "config",
            "module",
            "function",
            "class",
            "interface",
            "component",
            "middleware",
            "endpoint",
            "request",
            "response",
            "payload",
            "validation",
            "Docker",
            "Kubernetes",
            "TypeScript",
            "React",
            "Next.js",
            "\u5de5\u5177",
            "\u4e0a\u4e0b\u6587",
            "\u4f1a\u8bdd",
            "\u6570\u636e\u5e93",
            "\u811a\u672c",
            "\u6a21\u578b",
            "\u4ee3\u7801",
            "\u7f16\u7a0b",
            "\u8f6f\u4ef6",
            "\u5de5\u7a0b",
            "\u67b6\u6784",
            "\u524d\u7aef",
            "\u540e\u7aef",
            "\u63a5\u53e3",
            "\u8fc1\u79fb",
            "\u7f13\u5b58",
            "\u4ed3\u5e93",
            "\u63d0\u4ea4",
            "\u90e8\u7f72",
            "\u6d4b\u8bd5",
            "\u8c03\u8bd5",
            "\u5b89\u5168",
            "\u914d\u7f6e",
            "\u6a21\u5757",
            "\u51fd\u6570",
            "\u7c7b",
            "\u7ec4\u4ef6",
            "\u4e2d\u95f4\u4ef6",
            "\u7aef\u70b9",
            "\u8bf7\u6c42",
            "\u54cd\u5e94",
            "\u8f7d\u8377",
            "\u6821\u9a8c",
            "\u30c8\u30fc\u30af\u30f3",
            "\u6587\u8108",
            "\u30bb\u30c3\u30b7\u30e7\u30f3",
            "\u30b3\u30fc\u30c9",
            "\u30d7\u30ed\u30b0\u30e9\u30df\u30f3\u30b0",
            "\u30bd\u30d5\u30c8\u30a6\u30a7\u30a2",
            "\u30c7\u30fc\u30bf\u30d9\u30fc\u30b9",
            "\ud14c\uc2a4\ud2b8",
            "\ub514\ubc84\uadf8",
            "\ucf54\ub4dc",
            "\uc18c\ud504\ud2b8\uc6e8\uc5b4",
            "\ub370\uc774\ud130\ubca0\uc774\uc2a4"
        ]
    ],
    [
        "Legal, compliance, and risk",
        [
            "legal",
            "law",
            "compliance",
            "privacy",
            "copyright",
            "license",
            "audit",
            "liability",
            "policy",
            "contract",
            "clause",
            "case law",
            "risk",
            "brand compliance",
            "approval workflow",
            "rights management",
            "security",
            "permission",
            "secret",
            "\u6cd5\u5f8b",
            "\u6cd5\u89c4",
            "\u5408\u89c4",
            "\u9690\u79c1",
            "\u7248\u6743",
            "\u8bb8\u53ef",
            "\u5ba1\u8ba1",
            "\u8d23\u4efb",
            "\u653f\u7b56",
            "\u5408\u540c",
            "\u6761\u6b3e",
            "\u5224\u4f8b",
            "\u98ce\u9669",
            "\u54c1\u724c\u5408\u89c4",
            "\u5ba1\u6279\u6d41\u7a0b",
            "\u6743\u5229\u7ba1\u7406",
            "\u5b89\u5168",
            "\u6743\u9650",
            "\u5bc6\u94a5",
            "\u6cd5\u4ee4",
            "\u30b3\u30f3\u30d7\u30e9\u30a4\u30a2\u30f3\u30b9",
            "\u8457\u4f5c\u6a29",
            "\u5951\u7d04",
            "\u6761\u9805",
            "\u30ea\u30b9\u30af",
            "\ubc95\ub960",
            "\uaddc\uc815",
            "\uc900\uc218",
            "\uac1c\uc778\uc815\ubcf4",
            "\uc800\uc791\uad8c",
            "\uacc4\uc57d",
            "\uc870\ud56d",
            "\uc704\ud5d8",
            "cumplimiento",
            "cl\u00e1usula",
            "juridique",
            "conformit\u00e9",
            "rechtlich",
            "vertrag",
            "klausel",
            "jur\u00eddico",
            "conformidade"
        ]
    ],
    [
        "Strategy, planning, and progress",
        [
            "strategy",
            "plan",
            "milestone",
            "progress",
            "priority",
            "feasibility",
            "roadmap",
            "next step",
            "brand strategy",
            "brand management",
            "brand governance",
            "brand architecture",
            "brand system",
            "brand platform",
            "brand positioning",
            "positioning",
            "value proposition",
            "messaging",
            "narrative",
            "campaign",
            "marketing",
            "market research",
            "competitive analysis",
            "customer journey",
            "touchpoint",
            "channel",
            "content strategy",
            "digital management",
            "asset management",
            "brand audit",
            "brand equity",
            "brand consistency",
            "localization",
            "internationalization",
            "\u7b56\u7565",
            "\u8ba1\u5212",
            "\u8fdb\u5ea6",
            "\u9636\u6bb5",
            "\u4f18\u5148\u7ea7",
            "\u91cc\u7a0b\u7891",
            "\u53ef\u884c\u6027",
            "\u8def\u7ebf\u56fe",
            "\u4e0b\u4e00\u6b65",
            "\u54c1\u724c\u7b56\u7565",
            "\u54c1\u724c\u7ba1\u7406",
            "\u54c1\u724c\u6cbb\u7406",
            "\u54c1\u724c\u67b6\u6784",
            "\u54c1\u724c\u4f53\u7cfb",
            "\u54c1\u724c\u5e73\u53f0",
            "\u54c1\u724c\u5b9a\u4f4d",
            "\u4ef7\u503c\u4e3b\u5f20",
            "\u4f20\u64ad\u53e3\u5f84",
            "\u53d9\u4e8b",
            "\u8425\u9500",
            "\u5e02\u573a\u8c03\u7814",
            "\u7ade\u54c1\u5206\u6790",
            "\u5ba2\u6237\u65c5\u7a0b",
            "\u89e6\u70b9",
            "\u6e20\u9053",
            "\u5185\u5bb9\u7b56\u7565",
            "\u6570\u5b57\u5316\u7ba1\u7406",
            "\u8d44\u4ea7\u7ba1\u7406",
            "\u54c1\u724c\u5ba1\u8ba1",
            "\u54c1\u724c\u8d44\u4ea7",
            "\u54c1\u724c\u4e00\u81f4\u6027",
            "\u672c\u5730\u5316",
            "\u56fd\u9645\u5316",
            "\u6226\u7565",
            "\u8a08\u753b",
            "\u9032\u6357",
            "\u30d6\u30e9\u30f3\u30c9\u6226\u7565",
            "\ube0c\ub79c\ub4dc \uc804\ub7b5",
            "estrategia de marca",
            "strat\u00e9gie de marque",
            "markenstrategie",
            "estrat\u00e9gia de marca"
        ]
    ],
    [
        "Style, tone, audience, and interpretation",
        [
            "style",
            "tone",
            "audience",
            "voice",
            "positioning",
            "interpretation",
            "meaning",
            "wording",
            "quote",
            "visual identity",
            "identity system",
            "logo",
            "typography",
            "color palette",
            "layout",
            "grid",
            "guideline",
            "style guide",
            "tone of voice",
            "creative direction",
            "art direction",
            "concept",
            "moodboard",
            "prototype",
            "wireframe",
            "UI",
            "UX",
            "service design",
            "experience design",
            "information architecture",
            "usability",
            "accessibility",
            "\u98ce\u683c",
            "\u8bed\u6c14",
            "\u53d7\u4f17",
            "\u53e3\u5f84",
            "\u5b9a\u4f4d",
            "\u89e3\u91ca",
            "\u542b\u4e49",
            "\u63aa\u8f9e",
            "\u539f\u8bdd",
            "\u5f15\u7528",
            "\u89c6\u89c9\u8bc6\u522b",
            "\u8bc6\u522b\u7cfb\u7edf",
            "\u6807\u5fd7",
            "\u5b57\u4f53",
            "\u8272\u5f69",
            "\u914d\u8272",
            "\u7248\u5f0f",
            "\u7f51\u683c",
            "\u89c4\u8303",
            "\u98ce\u683c\u6307\u5357",
            "\u58f0\u97f3\u8bed\u8c03",
            "\u521b\u610f\u65b9\u5411",
            "\u827a\u672f\u6307\u5bfc",
            "\u6982\u5ff5",
            "\u60c5\u7eea\u677f",
            "\u539f\u578b",
            "\u7ebf\u6846\u56fe",
            "\u7528\u6237\u4f53\u9a8c",
            "\u670d\u52a1\u8bbe\u8ba1",
            "\u4f53\u9a8c\u8bbe\u8ba1",
            "\u4fe1\u606f\u67b6\u6784",
            "\u53ef\u7528\u6027",
            "\u65e0\u969c\u788d",
            "\u30b9\u30bf\u30a4\u30eb",
            "\u30c8\u30fc\u30f3",
            "\u8aad\u8005",
            "\u89e3\u91c8",
            "\u30ed\u30b4",
            "\u30bf\u30a4\u30dd\u30b0\u30e9\u30d5\u30a3",
            "\u30ab\u30e9\u30fc\u30d1\u30ec\u30c3\u30c8",
            "\u30d7\u30ed\u30c8\u30bf\u30a4\u30d7",
            "\uc0ac\uc6a9\uc790 \uacbd\ud5d8",
            "\uc2a4\ud0c0\uc77c",
            "\uc5b4\uc870",
            "estilo",
            "tono",
            "audiencia",
            "identidad visual",
            "typograf\u00eda",
            "ton",
            "public",
            "identit\u00e9 visuelle",
            "typographie",
            "stil",
            "zielgruppe",
            "visuelle identit\u00e4t",
            "typografie",
            "p\u00fablico",
            "identidade visual",
            "tipografia"
        ]
    ],
    [
        "Open questions, errors, and blockers",
        [
            "risk",
            "issue",
            "bug",
            "error",
            "warning",
            "unknown",
            "open question",
            "unresolved",
            "todo",
            "blocker",
            "\u7591\u70b9",
            "\u95ee\u9898",
            "\u9519\u8bef",
            "\u5f02\u5e38",
            "\u672a\u77e5",
            "\u5f85\u5b9a",
            "\u672a\u89e3\u51b3",
            "\u963b\u585e",
            "\u8ab2\u984c",
            "\u672a\u89e3\u6c7a",
            "\u30a8\u30e9\u30fc",
            "\u8b66\u544a",
            "\ubb38\uc81c",
            "\uc624\ub958",
            "\uacbd\uace0",
            "\ubbf8\ud574\uacb0",
            "bloqueador",
            "pendiente",
            "inconnu",
            "non r\u00e9solu",
            "bloquant",
            "unbekannt",
            "offen",
            "desconhecido",
            "pendente",
            "bloqueio"
        ]
    ]
]
)

TOPIC_MEMORY_PATTERNS = DEFAULT_TOPIC_MEMORY_PATTERNS
_ACTIVE_SUMMARY_TEMPLATE_PATH: Optional[pathlib.Path] = None
_SUMMARY_RESOURCES_CONFIGURED = False


def eprint(*parts: object) -> None:
    print(*parts, file=sys.stderr)


def now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def json_dump_line(obj: JsonObj) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def parse_jsonl_bytes(data: bytes, source_label: str = "JSONL") -> Tuple[List[JsonObj], List[str]]:
    records: List[JsonObj] = []
    raw_lines: List[str] = []
    for line_no, physical_line in enumerate(data.split(b"\n"), 1):
        line_bytes = physical_line[:-1] if physical_line.endswith(b"\r") else physical_line
        if line_no == 1 and line_bytes.startswith(b"\xef\xbb\xbf"):
            line_bytes = line_bytes[3:]
        try:
            line = line_bytes.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise ValueError(f"{source_label} line {line_no} is not valid UTF-8: {exc}") from exc
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except Exception as exc:  # pragma: no cover - reported to caller
            raise ValueError(f"line {line_no} is not valid JSON: {exc}") from exc
        if not isinstance(obj, dict):
            raise ValueError(f"line {line_no} is JSON but not an object")
        records.append(obj)
        raw_lines.append(line)
    return records, raw_lines


def read_jsonl(path: pathlib.Path) -> Tuple[List[JsonObj], List[str]]:
    return parse_jsonl_bytes(path.read_bytes(), source_label=str(path))


def jsonl_bytes(records: Sequence[JsonObj]) -> bytes:
    return ("".join(json_dump_line(obj) + "\n" for obj in records)).encode("utf-8")


def atomic_write_bytes(path: pathlib.Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.tmp-{uuid.uuid4().hex}")
    try:
        with temp_path.open("xb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, path)
        fsync_parent_directory(path)
    except Exception:
        try:
            temp_path.unlink()
        except FileNotFoundError:
            pass
        raise


def atomic_write_text(path: pathlib.Path, text: str) -> None:
    atomic_write_bytes(path, text.encode("utf-8"))


def write_jsonl(path: pathlib.Path, records: Sequence[JsonObj]) -> None:
    atomic_write_bytes(path, jsonl_bytes(records))


def fsync_parent_directory(path: pathlib.Path) -> bool:
    """Best-effort directory durability; unsupported platforms return False."""
    flags = getattr(os, "O_RDONLY", 0)
    directory_fd: Optional[int] = None
    try:
        directory_fd = os.open(str(path.parent), flags)
        os.fsync(directory_fd)
        return True
    except (OSError, AttributeError):
        return False
    finally:
        if directory_fd is not None:
            try:
                os.close(directory_fd)
            except OSError:
                pass


def publish_validated_jsonl(path: pathlib.Path, records: Sequence[JsonObj]) -> Dict[str, Any]:
    if is_under_claude_root(path):
        raise ValueError("candidate JSONL and process artifacts must be outside the entire .claude directory")
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.candidate-{uuid.uuid4().hex}.jsonl")
    candidate_bytes = jsonl_bytes(records)
    validation = validate_jsonl_bytes(candidate_bytes, source_label=path.name)
    if not validation.get("ok"):
        raise ValueError(f"generated candidate validation failed before publication: {validation.get('errors')}")
    if (
        validation.get("compact_metadata_historical_reference_warning_count")
        or validation.get("compact_metadata_chain_mismatch_count")
    ):
        raise ValueError("generated candidate compactMetadata snapshot is not current before publication")
    previous_bytes = path.read_bytes() if path.exists() else None
    try:
        with temp_path.open("xb") as f:
            f.write(candidate_bytes)
            f.flush()
            os.fsync(f.fileno())
        if sha256_hex(temp_path.read_bytes()) != sha256_hex(candidate_bytes):
            raise RuntimeError("staged candidate bytes changed before publication")
        os.replace(temp_path, path)
        fsync_parent_directory(path)
        if path.read_bytes() != candidate_bytes:
            if previous_bytes is None:
                path.unlink(missing_ok=True)
            else:
                atomic_write_bytes(path, previous_bytes)
            raise RuntimeError("published candidate bytes did not match the validated byte snapshot")
        return validation
    except Exception:
        try:
            temp_path.unlink()
        except FileNotFoundError:
            pass
        raise


def numbered_backup_path(path: pathlib.Path, backup_dir: Optional[pathlib.Path] = None) -> pathlib.Path:
    if backup_dir is None:
        base = path.with_suffix(path.suffix + ".backup")
        make_candidate = lambda i: path.with_suffix(path.suffix + f".backup{i}")
    else:
        base = backup_dir / f"{path.name}.backup"
        make_candidate = lambda i: backup_dir / f"{path.name}.backup{i}"
    if not base.exists():
        return base
    for i in range(1, 1000):
        candidate = make_candidate(i)
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"could not find free backup name for {path}")


def _exclusive_backup_from_bytes(
    path: pathlib.Path,
    source_bytes: bytes,
    backup_dir: Optional[pathlib.Path] = None,
) -> pathlib.Path:
    if backup_dir is None:
        candidates = [path.with_suffix(path.suffix + ".backup")]
        candidates.extend(path.with_suffix(path.suffix + f".backup{i}") for i in range(1, 1000))
    else:
        candidates = [backup_dir / f"{path.name}.backup"]
        candidates.extend(backup_dir / f"{path.name}.backup{i}" for i in range(1, 1000))
    for backup in candidates:
        backup.parent.mkdir(parents=True, exist_ok=True)
        stage = backup.with_name(f".{backup.name}.stage-{uuid.uuid4().hex}.tmp")
        try:
            with stage.open("xb") as f:
                f.write(source_bytes)
                f.flush()
                os.fsync(f.fileno())
            if stage.read_bytes() != source_bytes:
                raise RuntimeError(f"staged backup verification failed: {backup.name}")
            try:
                _publish_no_clobber(stage, backup)
            except FileExistsError:
                continue
            if backup.read_bytes() == source_bytes:
                fsync_parent_directory(backup)
                return backup
            # A concurrently replaced numbered path is not ours to delete.
        finally:
            try:
                stage.unlink()
            except FileNotFoundError:
                pass
    raise RuntimeError(f"could not find free backup name for {path}")


def create_backup(path: pathlib.Path, backup_dir: Optional[pathlib.Path] = None) -> pathlib.Path:
    if not path.exists():
        raise FileNotFoundError(f"cannot back up missing file: {path}")
    return _exclusive_backup_from_bytes(path, path.read_bytes(), backup_dir=backup_dir)


def _publish_no_clobber(source_path: pathlib.Path, destination_path: pathlib.Path) -> None:
    """Atomically create destination without replacing any concurrent claimant."""
    if destination_path.exists():
        raise FileExistsError(f"destination already exists: {destination_path.name}")
    try:
        os.link(source_path, destination_path)
    except FileExistsError:
        raise
    except OSError as exc:
        raise RuntimeError(
            "atomic no-clobber publication requires same-volume hard-link support"
        ) from exc
    fsync_parent_directory(destination_path)


def _ensure_verified_source_backup(
    path: pathlib.Path,
    source_bytes: bytes,
    backup: Optional[pathlib.Path],
    backup_dir: Optional[pathlib.Path],
) -> pathlib.Path:
    if backup is not None:
        try:
            if backup.read_bytes() == source_bytes:
                return backup
        except OSError:
            pass
    replacement = _exclusive_backup_from_bytes(path, source_bytes, backup_dir=backup_dir)
    if replacement.read_bytes() != source_bytes:
        raise RuntimeError("new numbered backup did not retain the verified source bytes")
    return replacement


def _restore_capture_no_clobber(
    capture_path: pathlib.Path,
    target_path: pathlib.Path,
    expected_bytes: bytes,
    *,
    validate_jsonl: bool,
) -> None:
    _publish_no_clobber(capture_path, target_path)
    restored_bytes = target_path.read_bytes()
    if restored_bytes != expected_bytes:
        raise RuntimeError("restored target bytes differ from the retained capture")
    if validate_jsonl:
        validation = validate_jsonl_bytes(restored_bytes, source_label=target_path.name)
        if not validation.get("ok"):
            raise RuntimeError(f"restored source validation failed: {validation.get('errors')}")
    try:
        if os.path.samefile(capture_path, target_path):
            capture_path.unlink()
    except (FileNotFoundError, OSError):
        pass
    fsync_parent_directory(target_path)


def _replace_file_after_validation(
    candidate_path: pathlib.Path,
    target_path: pathlib.Path,
    backup_dir: Optional[pathlib.Path] = None,
    expected_source_sha256: Optional[str] = None,
    expected_candidate_sha256: Optional[str] = None,
) -> Dict[str, Any]:
    # Low-level helper. Public live-session replacement must go through CLI
    # --replace-original so .claude scope, work-dir, and concurrency guards run.
    candidate_bytes = candidate_path.read_bytes()
    candidate_sha256 = sha256_hex(candidate_bytes)
    if expected_candidate_sha256 is not None and candidate_sha256 != expected_candidate_sha256:
        raise RuntimeError("candidate JSONL changed after validation; original file was not replaced")
    validation = validate_jsonl_bytes(candidate_bytes, source_label=candidate_path.name)
    if not validation.get("ok"):
        raise ValueError(f"candidate validation failed; original file was not replaced: {validation.get('errors')}")
    source_bytes = target_path.read_bytes()
    source_sha256 = sha256_hex(source_bytes)
    if expected_source_sha256 is not None and source_sha256 != expected_source_sha256:
        raise RuntimeError("input JSONL changed after candidate generation; original file was not replaced")
    tmp_replace = target_path.with_name(f".{target_path.name}.replace-{uuid.uuid4().hex}.tmp")
    old_capture = target_path.with_name(f".{target_path.name}.old-{uuid.uuid4().hex}.tmp")
    backup: Optional[pathlib.Path] = None
    published = False
    directory_fsync = False
    retain_old_capture = False
    external_target_preserved = False
    retained_rollback_capture: Optional[pathlib.Path] = None
    replaced_validation: Dict[str, Any] = {}
    try:
        with tmp_replace.open("xb") as f:
            f.write(candidate_bytes)
            f.flush()
            os.fsync(f.fileno())
        if sha256_hex(tmp_replace.read_bytes()) != candidate_sha256:
            raise RuntimeError("staged replacement bytes do not match the validated candidate snapshot")
        if target_path.read_bytes() != source_bytes:
            raise RuntimeError("input JSONL changed before backup; original file was not replaced")
        backup = _exclusive_backup_from_bytes(target_path, source_bytes, backup_dir=backup_dir)
        if target_path.read_bytes() != source_bytes:
            raise RuntimeError("input JSONL changed before replacement; original file was not replaced")
        os.replace(target_path, old_capture)
        directory_fsync = fsync_parent_directory(target_path) or directory_fsync
        captured_bytes = old_capture.read_bytes()
        if captured_bytes != source_bytes:
            raise RuntimeError("input JSONL changed during replacement capture; candidate was not installed")
        if target_path.exists():
            raise RuntimeError("input JSONL was recreated concurrently; external bytes were left in place")
        _publish_no_clobber(tmp_replace, target_path)
        published = True
        try:
            if os.path.samefile(tmp_replace, target_path):
                tmp_replace.unlink()
        except (FileNotFoundError, OSError):
            pass
        directory_fsync = fsync_parent_directory(target_path) or directory_fsync
        published_bytes = target_path.read_bytes()
        if sha256_hex(published_bytes) != candidate_sha256:
            raise RuntimeError("replacement target changed concurrently after publication; external bytes were left in place")
        replaced_validation = validate_jsonl_bytes(published_bytes, source_label=target_path.name)
        if not replaced_validation.get("ok"):
            raise ValueError(f"replacement validation failed: {replaced_validation.get('errors')}")
        backup = _ensure_verified_source_backup(target_path, source_bytes, backup, backup_dir)
        if old_capture.read_bytes() != source_bytes:
            raise RuntimeError("retained source capture changed before successful cleanup")
        old_capture.unlink()
        directory_fsync = fsync_parent_directory(target_path) or directory_fsync
    except Exception as exc:
        rollback_error: Optional[Exception] = None
        restored = False
        if backup is not None:
            try:
                backup = _ensure_verified_source_backup(target_path, source_bytes, backup, backup_dir)
            except Exception as backup_exc:
                rollback_error = backup_exc
        if old_capture.exists():
            try:
                if published and target_path.exists():
                    # Observe for diagnostics only. The following atomic capture,
                    # not this identity check, decides what is restored.
                    try:
                        target_path.read_bytes()
                    except OSError:
                        pass
                    rollback_capture = target_path.with_name(
                        f".{target_path.name}.rollback-{uuid.uuid4().hex}.tmp"
                    )
                    try:
                        os.replace(target_path, rollback_capture)
                    except FileNotFoundError:
                        rollback_capture = None
                    if rollback_capture is not None:
                        actual_target_bytes = rollback_capture.read_bytes()
                        if actual_target_bytes == candidate_bytes:
                            try:
                                _restore_capture_no_clobber(
                                    old_capture,
                                    target_path,
                                    source_bytes,
                                    validate_jsonl=True,
                                )
                                restored = True
                                if rollback_capture.read_bytes() == candidate_bytes:
                                    rollback_capture.unlink()
                            except FileExistsError:
                                external_target_preserved = True
                                retained_rollback_capture = rollback_capture
                        else:
                            external_target_preserved = True
                            try:
                                _restore_capture_no_clobber(
                                    rollback_capture,
                                    target_path,
                                    actual_target_bytes,
                                    validate_jsonl=False,
                                )
                            except FileExistsError:
                                retained_rollback_capture = rollback_capture
                            if backup is None or backup.read_bytes() != source_bytes:
                                raise RuntimeError("verified source backup is unavailable during concurrent-target recovery")
                            if old_capture.read_bytes() == source_bytes:
                                old_capture.unlink()
                elif target_path.exists():
                    external_target_preserved = True
                    if backup is None or backup.read_bytes() != source_bytes:
                        raise RuntimeError("verified source backup is unavailable during concurrent-target recovery")
                    if old_capture.read_bytes() == source_bytes:
                        old_capture.unlink()
                else:
                    try:
                        _restore_capture_no_clobber(
                            old_capture,
                            target_path,
                            source_bytes,
                            validate_jsonl=True,
                        )
                        restored = True
                    except FileExistsError:
                        external_target_preserved = True
            except Exception as restore_exc:
                rollback_error = restore_exc
                retain_old_capture = old_capture.exists()
        if rollback_error is not None:
            backup_label = backup.name if backup is not None else "none"
            capture_label = old_capture.name if retain_old_capture else "none"
            rollback_label = retained_rollback_capture.name if retained_rollback_capture is not None else "none"
            raise RuntimeError(
                f"replacement failed and rollback also failed; retain backup {backup_label}; "
                f"retained source capture {capture_label}; retained concurrent capture {rollback_label}; "
                f"replacement_error={exc}; rollback_error={rollback_error}"
            ) from exc
        if external_target_preserved:
            backup_label = backup.name if backup is not None else "none"
            captured_label = retained_rollback_capture.name if retained_rollback_capture is not None else "none"
            raise RuntimeError(
                "replacement stopped because the target was recreated concurrently; external bytes were preserved; "
                f"verified original backup retained as {backup_label}; retained concurrent capture={captured_label}"
            ) from exc
        if restored:
            raise RuntimeError(f"replacement failed and original bytes were restored: {exc}") from exc
        raise
    finally:
        transients = [tmp_replace]
        if not retain_old_capture:
            transients.append(old_capture)
        for transient in transients:
            try:
                transient.unlink()
            except FileNotFoundError:
                pass
    if backup is None:
        raise AssertionError("replacement completed without an auditable backup")
    return {
        "backup_path": backup,
        "validation": replaced_validation,
        "source_sha256": source_sha256,
        "candidate_sha256": candidate_sha256,
        "published_sha256": candidate_sha256,
        "parent_directory_fsync": directory_fsync,
    }


def is_same_or_inside(path: pathlib.Path, possible_parent: pathlib.Path) -> bool:
    try:
        resolved_path = path.resolve()
        resolved_parent = possible_parent.resolve()
    except OSError as exc:
        raise RuntimeError(f"cannot safely resolve path containment: {exc}") from exc
    return resolved_path == resolved_parent or resolved_parent in resolved_path.parents


def path_self_and_parents(path: pathlib.Path) -> List[pathlib.Path]:
    try:
        resolved = path.resolve(strict=False)
    except OSError as exc:
        raise RuntimeError(f"cannot safely resolve path ancestry: {exc}") from exc
    return [resolved, *resolved.parents]


def claude_root_ancestor(path: pathlib.Path) -> Optional[pathlib.Path]:
    for node in path_self_and_parents(path):
        if node.name.lower() == ".claude":
            return node
    return None


def is_under_claude_projects(path: pathlib.Path) -> bool:
    for node in path_self_and_parents(path):
        if node.name.lower() == "projects" and node.parent.name.lower() == ".claude":
            return True
    return False


def is_under_claude_root(path: pathlib.Path) -> bool:
    return claude_root_ancestor(path) is not None


def require_live_session_jsonl(path: pathlib.Path) -> None:
    if path.suffix.lower() != ".jsonl":
        raise ValueError("--replace-original requires an existing .jsonl session file")
    try:
        is_file = path.is_file()
    except OSError as exc:
        raise RuntimeError(f"cannot safely inspect live session target: {exc}") from exc
    if not is_file:
        raise ValueError("--replace-original requires an existing regular .jsonl session file")


def byte_len(s: str) -> int:
    return len(s.encode("utf-8", errors="replace")) + 1


def estimate_tokens(text: str) -> int:
    # Conservative, dependency-free planning estimate. It is intentionally
    # higher for scripts and symbols that tokenizers commonly split densely.
    if not text:
        return 0
    weighted = 0.0
    ascii_chars = 0
    for ch in text:
        cp = ord(ch)
        if cp < 0x80:
            ascii_chars += 1
            continue
        if (
            0x3400 <= cp <= 0x4DBF
            or 0x4E00 <= cp <= 0x9FFF
            or 0xF900 <= cp <= 0xFAFF
            or 0x20000 <= cp <= 0x323AF
            or 0x3040 <= cp <= 0x30FF
            or 0x31F0 <= cp <= 0x31FF
            or 0xAC00 <= cp <= 0xD7AF
            or 0x1100 <= cp <= 0x11FF
        ):
            weighted += 1.3
        elif cp > 0xFFFF or unicodedata.category(ch).startswith(("S", "M")):
            weighted += 1.5
        else:
            weighted += 0.8
    return max(1, int(weighted + ascii_chars / 4 + 0.999))


def estimate_records_tokens(records: Sequence[JsonObj]) -> int:
    total = 0
    for obj in records:
        payload: Any = None
        if is_api_message(obj):
            # Token accounting must use the complete retained message shape.
            # Display/evidence helpers intentionally truncate, so they are not
            # suitable for a publication ceiling.
            payload = {
                key: value
                for key, value in obj.items()
                if key not in {"uuid", "parentUuid", "sessionId", "timestamp", "cwd", "version"}
            }
        elif obj.get("type") == "attachment" and isinstance(obj.get("attachment"), dict):
            payload = obj.get("attachment")
        elif obj.get("type") == "system":
            payload = {
                key: obj.get(key)
                for key in ("subtype", "content", "error", "compactMetadata")
                if key in obj
            }
        if payload is None:
            continue
        serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        total += estimate_tokens(serialized) + 12
    return total


def effective_target_ratio_for_tokens(
    records: Sequence[JsonObj],
    target_ratio: float,
    target_estimated_tokens: Optional[int],
) -> Tuple[float, int]:
    input_estimated_tokens = estimate_records_tokens(records)
    if target_estimated_tokens is None or input_estimated_tokens <= 0:
        return target_ratio, input_estimated_tokens
    token_ratio = target_estimated_tokens / input_estimated_tokens
    return max(0.01, min(target_ratio, token_ratio)), input_estimated_tokens


def stable_digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:16]


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_sha256(path: pathlib.Path) -> str:
    return sha256_hex(path.read_bytes())


def file_digest_prefix(path: pathlib.Path) -> str:
    return file_sha256(path)[:16]


def public_path_label(path: Optional[pathlib.Path]) -> Optional[str]:
    if path is None:
        return None
    return path.name


def anonymous_artifact_label(path: Optional[pathlib.Path], label: str) -> Optional[str]:
    return label if path is not None else None


def require_summary_char_budget(summary_char_budget: int) -> None:
    if summary_char_budget < MIN_SUMMARY_CHAR_BUDGET:
        raise ValueError(
            f"summary character budget must be at least {MIN_SUMMARY_CHAR_BUDGET}; "
            "smaller values cannot carry a meaningful compact summary"
        )


def read_optional_text(path: Optional[pathlib.Path]) -> Tuple[str, Optional[str], int]:
    if path is None:
        return "", None, 0
    raw = path.read_bytes()
    text = raw.decode("utf-8-sig", errors="strict")
    if not text.strip():
        raise ValueError("the supplied external handoff summary is empty or whitespace-only")
    return text, sha256_hex(raw), len(raw)


def physical_text_lines(text: str) -> List[str]:
    """Split only on LF while retaining every line terminator and blank line."""
    if not text:
        return []
    parts = text.split("\n")
    lines = [part + "\n" for part in parts[:-1]]
    if parts[-1] or not lines:
        lines.append(parts[-1])
    if "".join(lines) != text:
        raise AssertionError("internal error: physical text line split is not lossless")
    return lines


def truncate(text: str, limit: int) -> str:
    if limit <= 0:
        return ""
    text = str(text)
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 32)].rstrip() + f"\n...[truncated {len(text) - limit} chars]"


def is_noisy_text(text: str) -> bool:
    if not text:
        return False
    if "\ufffd" in text:
        return True
    # Common Windows/terminal mojibake fragments seen in failed tool output.
    bad_markers = ("锟", "\\223", "\\211", "\\226", "\\255")
    return sum(text.count(x) for x in bad_markers) >= 3


def one_line(text: str, limit: int = 220) -> str:
    text = re.sub(r"\s+", " ", str(text)).strip()
    return truncate(text, limit).replace("\n", " ")


def block_text(block: Any) -> str:
    if isinstance(block, str):
        return block
    if not isinstance(block, dict):
        return ""
    t = block.get("type")
    if t == "text":
        return str(block.get("text", ""))
    if t == "tool_use":
        name = block.get("name", "tool")
        inp = block.get("input", {})
        return f"[tool_use:{name}] {json.dumps(inp, ensure_ascii=False)[:800]}"
    if t == "tool_result":
        content = block.get("content", "")
        if isinstance(content, list):
            content = " ".join(block_text(x) for x in content)
        return f"[tool_result] {content}"
    if "text" in block:
        return str(block.get("text", ""))
    return ""


def semantic_block_text(block: Any) -> str:
    """Return human/model prose while excluding tool payloads and results."""
    if isinstance(block, str):
        return block
    if not isinstance(block, dict):
        return ""
    block_type = block.get("type")
    if block_type == "text":
        value = block.get("text")
        return value if isinstance(value, str) else ""
    if block_type == "thinking":
        value = block.get("thinking")
        if not isinstance(value, str):
            value = block.get("text")
        return value if isinstance(value, str) else ""
    if block_type in (None, "") and isinstance(block.get("text"), str):
        return str(block.get("text"))
    return ""


def semantic_message_text(obj: JsonObj) -> str:
    """Extract complete conversational prose, including assistant thinking blocks."""
    msg = obj.get("message")
    content: Any = None
    if isinstance(msg, dict):
        content = msg.get("content", "")
    elif isinstance(msg, str):
        content = msg
    elif "content" in obj:
        content = obj.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(filter(None, (semantic_block_text(block) for block in content)))
    return semantic_block_text(content)


def message_text(obj: JsonObj) -> str:
    msg = obj.get("message")
    if isinstance(msg, dict):
        content = msg.get("content", "")
        if isinstance(content, list):
            return "\n".join(filter(None, (block_text(x) for x in content)))
        if isinstance(content, str):
            return content
        return block_text(content)
    if isinstance(msg, str):
        return msg
    if "content" in obj:
        c = obj.get("content")
        if isinstance(c, str):
            return c
        if isinstance(c, list):
            return "\n".join(filter(None, (block_text(x) for x in c)))
    return ""


def attachment_text(obj: JsonObj) -> str:
    att = obj.get("attachment")
    if not isinstance(att, dict):
        return ""
    pieces = []
    for key in ("type", "hookName", "hookEvent", "command", "content", "stdout", "stderr"):
        val = att.get(key)
        if val:
            pieces.append(f"{key}={one_line(str(val), 260)}")
    return "; ".join(pieces)


def tool_result_text(obj: JsonObj) -> str:
    tr = obj.get("toolUseResult")
    if tr is None:
        return ""
    if isinstance(tr, str):
        return tr
    if isinstance(tr, dict):
        pieces = []
        for key in ("type", "filePath", "stdout", "stderr", "content", "output", "error", "message"):
            val = tr.get(key)
            if val:
                pieces.append(f"{key}={one_line(str(val), 320)}")
        return "; ".join(pieces) if pieces else json.dumps(tr, ensure_ascii=False)[:1200]
    return json.dumps(tr, ensure_ascii=False)[:1200]


def record_text(obj: JsonObj) -> str:
    t = obj.get("type")
    if t in ("user", "assistant"):
        txt = message_text(obj)
        tr = tool_result_text(obj)
        return "\n".join(x for x in (txt, tr) if x)
    if t == "attachment":
        return attachment_text(obj)
    if t == "system":
        return " ".join(str(obj.get(k, "")) for k in ("subtype", "content", "error") if obj.get(k))
    if t == "file-history-snapshot":
        snap = obj.get("snapshot")
        if isinstance(snap, dict):
            tracked = snap.get("trackedFileBackups", {})
            return f"file-history-snapshot tracked={len(tracked) if isinstance(tracked, dict) else 'unknown'}"
    return ""


def is_human_user_record(obj: JsonObj) -> bool:
    if obj.get("type") != "user":
        return False
    if obj.get("isCompactSummary") is True:
        return False
    msg = obj.get("message")
    if not isinstance(msg, dict) or msg.get("role") != "user":
        return False
    content = msg.get("content")
    if isinstance(content, str):
        stripped = content.strip()
        if not stripped:
            return False
        if stripped.startswith("<local-command-") or stripped.startswith("<command-"):
            return False
        return True
    if isinstance(content, list):
        return bool(semantic_message_text(obj).strip())
    return False


def is_tool_result_user_record(obj: JsonObj) -> bool:
    return obj.get("type") == "user" and (
        obj.get("toolUseResult") is not None
        or bool(obj.get("sourceToolAssistantUUID"))
        or any(isinstance(block, dict) and block.get("type") == "tool_result" for block in content_blocks(obj))
    )


def extract_paths(text: str) -> List[str]:
    out: List[str] = []
    for m in PATH_RE.finditer(text):
        val = m.group(0).strip(".,;:，。；：)")
        if len(val) >= 3:
            out.append(val)
    return out


def common_fields(records: Sequence[JsonObj]) -> JsonObj:
    keys = ("userType", "entrypoint", "cwd", "sessionId", "version", "gitBranch", "permissionMode")
    out: JsonObj = {}
    for key in keys:
        counts = collections.Counter()
        for obj in records:
            val = obj.get(key)
            if isinstance(val, (str, int, float, bool)) or val is None:
                if val not in ("", None):
                    counts[val] += 1
        if counts:
            out[key] = counts.most_common(1)[0][0]
    return out


def choose_recent_start(
    records: Sequence[JsonObj],
    raw_lines: Sequence[str],
    input_bytes: int,
    target_ratio: float,
    min_recent_records: int,
    summary_budget_bytes: int,
) -> int:
    target_bytes = max(4096, int(input_bytes * target_ratio))
    recent_budget = max(4096, target_bytes - summary_budget_bytes)
    start = len(records)
    used = 0
    while start > 0:
        next_len = byte_len(raw_lines[start - 1])
        must_keep_more = len(records) - start < min_recent_records
        if not must_keep_more and used + next_len > recent_budget:
            break
        used += next_len
        start -= 1
    if start <= 2 and len(records) > min_recent_records:
        start = max(0, len(records) - min_recent_records)
    return start


def content_blocks(obj: JsonObj) -> List[Any]:
    msg = obj.get("message")
    if not isinstance(msg, dict):
        return []
    content = msg.get("content")
    if isinstance(content, list):
        return content
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    return []


def tool_use_ids(obj: JsonObj) -> List[str]:
    ids: List[str] = []
    for block in content_blocks(obj):
        if isinstance(block, dict) and block.get("type") == "tool_use" and isinstance(block.get("id"), str):
            ids.append(block["id"])
    return ids


def tool_result_ids(obj: JsonObj) -> List[str]:
    ids: List[str] = []
    for block in content_blocks(obj):
        if isinstance(block, dict) and block.get("type") == "tool_result":
            tool_id = block.get("tool_use_id") or block.get("toolUseID")
            if isinstance(tool_id, str):
                ids.append(tool_id)
    return ids


def source_tool_assistant_uuid(obj: JsonObj) -> Optional[str]:
    source_uuid = obj.get("sourceToolAssistantUUID")
    return source_uuid if isinstance(source_uuid, str) else None


def ordered_subsequence(items: Sequence[str], expected: Sequence[str]) -> bool:
    """Return true when items appear in expected in the same order.

    Claude Code branches can preserve only part of a multi-tool assistant turn.
    Validation therefore checks order and membership, not strict full equality.
    """
    if not items or not expected:
        return False
    pos = 0
    for item in items:
        while pos < len(expected) and expected[pos] != item:
            pos += 1
        if pos >= len(expected):
            return False
        pos += 1
    return True


def is_api_message(obj: JsonObj) -> bool:
    return obj.get("type") in {"user", "assistant"} and isinstance(obj.get("message"), dict)


def api_role(obj: JsonObj) -> Optional[str]:
    msg = obj.get("message")
    if isinstance(msg, dict) and isinstance(msg.get("role"), str):
        return msg.get("role")
    return None


def message_id(obj: JsonObj) -> Optional[str]:
    msg = obj.get("message")
    if isinstance(msg, dict) and isinstance(msg.get("id"), str):
        return msg.get("id")
    return None


def latest_last_prompt_entry(records: Sequence[JsonObj]) -> Optional[Tuple[int, JsonObj]]:
    """Return the physically last last-prompt record, even when malformed."""
    for idx in range(len(records) - 1, -1, -1):
        if records[idx].get("type") == "last-prompt":
            return idx, records[idx]
    return None


def latest_last_prompt_leaf(records: Sequence[JsonObj]) -> Optional[str]:
    entry = latest_last_prompt_entry(records)
    if entry is None:
        return None
    leaf = entry[1].get("leafUuid")
    return leaf if isinstance(leaf, str) and leaf else None


def latest_physical_uuid(records: Sequence[JsonObj]) -> Optional[str]:
    for obj in reversed(records):
        uid = obj.get("uuid")
        if isinstance(uid, str) and uid:
            return uid
    return None


def chain_trace_from_leaf(records: Sequence[JsonObj], leaf: Optional[str]) -> Dict[str, Any]:
    trace: Dict[str, Any] = {
        "leafUuid": leaf,
        "chain": [],
        "missingUuid": None,
        "loopUuid": None,
        "malformedParentUuid": None,
        "malformedParentType": None,
    }
    if leaf is None:
        return trace
    uuid_to_record = {obj.get("uuid"): obj for obj in records if isinstance(obj.get("uuid"), str)}
    chain: List[JsonObj] = []
    seen: set = set()
    cur: Optional[str] = leaf
    while cur:
        if cur in seen:
            trace["loopUuid"] = cur
            trace["chain"] = list(reversed(chain))
            return trace
        seen.add(cur)
        obj = uuid_to_record.get(cur)
        if obj is None:
            trace["missingUuid"] = cur
            trace["chain"] = list(reversed(chain))
            return trace
        chain.append(obj)
        parent = obj.get("parentUuid")
        if parent is None:
            cur = None
        elif isinstance(parent, str) and parent:
            cur = parent
        else:
            trace["malformedParentUuid"] = obj.get("uuid")
            trace["malformedParentType"] = type(parent).__name__
            trace["chain"] = list(reversed(chain))
            return trace
    trace["chain"] = list(reversed(chain))
    return trace


def chain_from_leaf(records: Sequence[JsonObj], leaf: Optional[str]) -> List[JsonObj]:
    return list(chain_trace_from_leaf(records, leaf).get("chain") or [])


def line_by_uuid(records: Sequence[JsonObj]) -> Dict[str, int]:
    return {obj.get("uuid"): idx for idx, obj in enumerate(records, 1) if isinstance(obj.get("uuid"), str)}


def analyze_chain_physical_order(records: Sequence[JsonObj], chain: Sequence[JsonObj]) -> Dict[str, Any]:
    uuid_to_index = {
        obj.get("uuid"): idx
        for idx, obj in enumerate(records)
        if isinstance(obj.get("uuid"), str) and obj.get("uuid")
    }
    indexes = [uuid_to_index.get(obj.get("uuid")) for obj in chain]
    inversions: List[JsonObj] = []
    for position in range(1, len(chain)):
        parent_index = indexes[position - 1]
        child_index = indexes[position]
        if not isinstance(parent_index, int) or not isinstance(child_index, int) or child_index > parent_index:
            continue
        parent = chain[position - 1]
        child = chain[position]
        parent_session = parent.get("sessionId")
        child_session = child.get("sessionId")
        compatible = (
            parent.get("type") == "attachment"
            and child.get("type") == "attachment"
            and isinstance(parent_session, str)
            and bool(parent_session)
            and parent_session == child_session
        )
        inversions.append(
            {
                "position": position,
                "parentType": parent.get("type"),
                "childType": child.get("type"),
                "distance": parent_index - child_index,
                "attachmentCompatibility": compatible,
            }
        )
    incompatible = [item for item in inversions if not item["attachmentCompatibility"]]
    return {
        "ok": not incompatible,
        "inversionCount": len(inversions),
        "compatibilityEdgeCount": len(inversions) - len(incompatible),
        "incompatibleEdgeCount": len(incompatible),
        "incompatibleSamples": incompatible[:20],
    }


def analyze_session_lineage(chain: Sequence[JsonObj], authority_session: Any) -> Dict[str, Any]:
    string_sessions = [
        (position, obj.get("sessionId"))
        for position, obj in enumerate(chain)
        if isinstance(obj.get("sessionId"), str) and obj.get("sessionId")
    ]
    unique_sessions = list(dict.fromkeys(session for _, session in string_sessions))
    result: Dict[str, Any] = {
        "ok": True,
        "reason": None,
        "compatibility": False,
        "sessionCount": len(set(unique_sessions)),
        "runCount": 0,
        "transitionCount": 0,
        "currentSessionId": unique_sessions[-1] if unique_sessions else None,
        "currentSessionStartPosition": 0,
        "currentSessionRecordCount": len(chain),
        "runsDigest": None,
    }
    if not string_sessions:
        return result

    runs: List[JsonObj] = []
    for position, session_id in string_sessions:
        if not runs or runs[-1]["sessionId"] != session_id:
            runs.append({"sessionId": session_id, "start": position, "end": position})
        else:
            runs[-1]["end"] = position
    run_ids = [str(run["sessionId"]) for run in runs]
    result["runCount"] = len(runs)
    result["transitionCount"] = max(0, len(runs) - 1)
    result["runsDigest"] = stable_digest("\n".join(run_ids))
    final_session = run_ids[-1]
    result["currentSessionId"] = final_session
    result["currentSessionStartPosition"] = int(runs[-1]["start"])
    result["currentSessionRecordCount"] = len(chain) - int(runs[-1]["start"])

    if len(runs) == 1:
        if isinstance(authority_session, str) and authority_session and authority_session != final_session:
            result["ok"] = False
            result["reason"] = "authority-session-does-not-match-chain"
        return result

    result["compatibility"] = True
    if len(string_sessions) != len(chain):
        result["ok"] = False
        result["reason"] = "mixed-session-lineage-has-missing-session-id"
    elif len(run_ids) != len(set(run_ids)):
        result["ok"] = False
        result["reason"] = "session-lineage-returns-to-an-earlier-session"
    elif not isinstance(authority_session, str) or not authority_session:
        result["ok"] = False
        result["reason"] = "mixed-session-lineage-requires-authority-session"
    elif authority_session != final_session:
        result["ok"] = False
        result["reason"] = "authority-session-does-not-match-final-lineage-session"
    else:
        leaf_session = chain[-1].get("sessionId") if chain else None
        if leaf_session != final_session:
            result["ok"] = False
            result["reason"] = "leaf-session-does-not-match-final-lineage-session"
    return result


def _tool_result_only_api_message(obj: JsonObj, allowed_ids: set) -> bool:
    if api_role(obj) != "user":
        return False
    ids = tool_result_ids(obj)
    if not ids or not set(ids).issubset(allowed_ids):
        return False
    message = obj.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    return isinstance(content, list) and all(
        isinstance(block, dict) and block.get("type") == "tool_result" for block in content
    )


def _allowed_post_prompt_closure(obj: JsonObj, pending_tool_ids: set) -> Tuple[bool, str]:
    if is_api_message(obj):
        if _tool_result_only_api_message(obj, pending_tool_ids):
            pending_tool_ids.difference_update(tool_result_ids(obj))
            return True, "tool_result_closure"
        return False, "ordinary_api_message"
    return False, f"unsupported_record_type:{obj.get('type')}"


def choose_resume_leaf_info(
    records: Sequence[JsonObj],
    max_post_prompt_extension: int = 0,
    resume_leaf_override: Optional[str] = None,
) -> Dict[str, Any]:
    """Analyze the authoritative resume path without silently selecting another leaf."""
    last_prompt_entry = latest_last_prompt_entry(records)
    physical_leaf = latest_physical_uuid(records)
    duplicate_uuids = sorted(
        uid for uid, count in collections.Counter(
            obj.get("uuid") for obj in records if isinstance(obj.get("uuid"), str) and obj.get("uuid")
        ).items() if count > 1
    )
    info: Dict[str, Any] = {
        "ok": False,
        "status": "absent" if last_prompt_entry is None else "unvalidated",
        "errors": [],
        "warnings": [],
        "lastPromptIndex": last_prompt_entry[0] if last_prompt_entry else None,
        "lastPromptLine": last_prompt_entry[0] + 1 if last_prompt_entry else None,
        "lastPromptTemplate": copy.deepcopy(last_prompt_entry[1]) if last_prompt_entry else None,
        "promptLeafUuid": last_prompt_entry[1].get("leafUuid") if last_prompt_entry else None,
        "physicalLeafUuid": physical_leaf,
        "selectedLeafUuid": None,
        "selectedLeafSource": "manual-override" if resume_leaf_override else "last-prompt",
        "manualOverride": bool(resume_leaf_override),
        "duplicateUuids": duplicate_uuids,
        "postLastPromptExtensionRecords": 0,
        "postLastPromptExtensionReasons": [],
        "postLastPromptExtensionStartLine": None,
        "postLastPromptExtensionEndLine": None,
        "postLastPromptExtensionUuids": [],
        "promptChainMissingUuid": None,
        "promptChainLoopUuid": None,
        "promptChainMalformedParentUuid": None,
        "promptChainMalformedParentType": None,
        "nonMonotonicEdgeCount": 0,
        "nonMonotonicCompatibilityEdgeCount": 0,
        "sessionLineageCompatibility": False,
        "sessionLineageSessionCount": 0,
        "sessionLineageRunCount": 0,
        "sessionLineageTransitionCount": 0,
        "sessionLineageRunsDigest": None,
        "currentSessionStartPosition": 0,
        "currentSessionRecordCount": 0,
        "currentSessionId": None,
        "activeChainIndexes": [],
        "activeChainUuids": [],
        "authoritySessionId": last_prompt_entry[1].get("sessionId") if last_prompt_entry else None,
    }
    if duplicate_uuids:
        info["status"] = "duplicate-uuid"
        info["errors"].append(f"duplicate uuid values make resume topology ambiguous: {duplicate_uuids[:20]}")
        return info
    if last_prompt_entry is None:
        info["errors"].append("strict active-chain mode requires a last-prompt record")
        return info

    prompt_index, prompt_record = last_prompt_entry
    prompt_leaf = resume_leaf_override or prompt_record.get("leafUuid")
    if not isinstance(prompt_leaf, str) or not prompt_leaf:
        info["status"] = "malformed"
        info["errors"].append("authoritative last-prompt leafUuid is missing or malformed")
        return info
    info["selectedLeafUuid"] = prompt_leaf
    trace = chain_trace_from_leaf(records, prompt_leaf)
    info["promptChainMissingUuid"] = trace.get("missingUuid")
    info["promptChainLoopUuid"] = trace.get("loopUuid")
    info["promptChainMalformedParentUuid"] = trace.get("malformedParentUuid")
    info["promptChainMalformedParentType"] = trace.get("malformedParentType")
    if trace.get("missingUuid"):
        info["status"] = "dangling"
        info["errors"].append(f"authoritative resume chain references missing uuid: {trace.get('missingUuid')}")
        return info
    if trace.get("loopUuid"):
        info["status"] = "loop"
        info["errors"].append(f"authoritative resume chain contains a loop at uuid: {trace.get('loopUuid')}")
        return info
    if trace.get("malformedParentUuid"):
        info["status"] = "malformed-parent"
        info["errors"].append(
            "authoritative resume chain contains a non-null, non-empty-string parentUuid "
            f"on uuid {trace.get('malformedParentUuid')} (type {trace.get('malformedParentType')})"
        )
        return info
    chain = list(trace.get("chain") or [])
    if not chain:
        info["status"] = "dangling"
        info["errors"].append("authoritative resume chain is empty")
        return info
    uuid_to_index = {
        obj.get("uuid"): idx for idx, obj in enumerate(records)
        if isinstance(obj.get("uuid"), str) and obj.get("uuid")
    }
    chain_indexes = [uuid_to_index[obj["uuid"]] for obj in chain]
    order_info = analyze_chain_physical_order(records, chain)
    info["nonMonotonicEdgeCount"] = order_info["inversionCount"]
    info["nonMonotonicCompatibilityEdgeCount"] = order_info["compatibilityEdgeCount"]
    if not order_info["ok"]:
        info["status"] = "non-monotonic"
        info["errors"].append(
            "authoritative resume chain has non-monotonic physical parent edges outside the "
            "same-session attachment compatibility rule"
        )
        return info
    if order_info["compatibilityEdgeCount"]:
        info["warnings"].append(
            f"accepted {order_info['compatibilityEdgeCount']} same-session attachment parent edges "
            "whose physical lines are out of logical chain order; output will normalize logical order"
        )
    authority_session = prompt_record.get("sessionId")
    lineage_info = analyze_session_lineage(chain, authority_session)
    info["sessionLineageCompatibility"] = lineage_info["compatibility"]
    info["sessionLineageSessionCount"] = lineage_info["sessionCount"]
    info["sessionLineageRunCount"] = lineage_info["runCount"]
    info["sessionLineageTransitionCount"] = lineage_info["transitionCount"]
    info["sessionLineageRunsDigest"] = lineage_info["runsDigest"]
    info["currentSessionStartPosition"] = lineage_info["currentSessionStartPosition"]
    info["currentSessionRecordCount"] = lineage_info["currentSessionRecordCount"]
    info["currentSessionId"] = lineage_info["currentSessionId"]
    if not lineage_info["ok"]:
        info["status"] = "session-mismatch"
        info["errors"].append(
            "authoritative resume chain has an unsafe sessionId lineage: "
            f"{lineage_info['reason']}"
        )
        return info
    if lineage_info["compatibility"]:
        info["warnings"].append(
            f"accepted one-way session lineage with {lineage_info['transitionCount']} transition(s); "
            "all sessions before the final authority session must be summarized"
        )

    if max_post_prompt_extension > 0:
        extension_pairs = list(enumerate(records[prompt_index + 1 :], start=prompt_index + 1))
        if extension_pairs:
            if len(extension_pairs) > max_post_prompt_extension:
                info["status"] = "extension-limit"
                info["errors"].append(
                    f"post-last-prompt closure has {len(extension_pairs)} UUID records, exceeding limit {max_post_prompt_extension}"
                )
                return info
            expected_parent = prompt_leaf
            expected_session = prompt_record.get("sessionId")
            if not isinstance(expected_session, str) or not expected_session:
                info["status"] = "session-mismatch"
                info["errors"].append("post-last-prompt closure requires a non-empty authority sessionId")
                return info
            pending_tool_ids = set(tool_use_ids(chain[-1]))
            extension_reasons: List[str] = []
            for idx, obj in extension_pairs:
                if not isinstance(obj.get("uuid"), str) or not obj.get("uuid"):
                    info["status"] = "extension-unsafe"
                    info["errors"].append(
                        f"post-last-prompt record L{idx + 1} has no UUID and breaks the physical closure sequence"
                    )
                    return info
                if obj.get("parentUuid") != expected_parent:
                    info["status"] = "extension-branch"
                    info["errors"].append(f"post-last-prompt record L{idx + 1} is not a direct linear descendant")
                    return info
                obj_session = obj.get("sessionId")
                if not isinstance(obj_session, str) or not obj_session or obj_session != expected_session:
                    info["status"] = "session-mismatch"
                    info["errors"].append(
                        f"post-last-prompt record L{idx + 1} does not have the exact authority sessionId"
                    )
                    return info
                allowed, reason = _allowed_post_prompt_closure(obj, pending_tool_ids)
                if not allowed:
                    info["status"] = "extension-unsafe"
                    info["errors"].append(f"post-last-prompt record L{idx + 1} is not a safe closure: {reason}")
                    return info
                extension_reasons.append(reason)
                expected_parent = obj.get("uuid")
            if pending_tool_ids:
                info["status"] = "extension-unsafe"
                info["errors"].append(
                    f"post-last-prompt closure leaves pending tool_use ids unresolved: {sorted(pending_tool_ids)[:20]}"
                )
                return info
            selected_extension_records = [obj for _, obj in extension_pairs]
            chain.extend(selected_extension_records)
            chain_indexes.extend(idx for idx, _ in extension_pairs)
            info["selectedLeafUuid"] = expected_parent
            info["selectedLeafSource"] = "explicit-post-last-prompt-closure"
            info["postLastPromptExtensionRecords"] = len(extension_pairs)
            info["postLastPromptExtensionReasons"] = sorted(set(extension_reasons))
            info["postLastPromptExtensionStartLine"] = extension_pairs[0][0] + 1
            info["postLastPromptExtensionEndLine"] = extension_pairs[-1][0] + 1
            info["postLastPromptExtensionUuids"] = [obj.get("uuid") for _, obj in extension_pairs]
            info["currentSessionRecordCount"] = int(info.get("currentSessionRecordCount") or 0) + len(extension_pairs)

    info["status"] = "valid"
    info["ok"] = True
    info["activeChainIndexes"] = chain_indexes
    info["activeChainUuids"] = [obj.get("uuid") for obj in chain]
    return info


def require_resume_leaf_info(
    records: Sequence[JsonObj],
    max_post_prompt_extension: int = 0,
    resume_leaf_override: Optional[str] = None,
) -> Dict[str, Any]:
    info = choose_resume_leaf_info(records, max_post_prompt_extension, resume_leaf_override)
    if not info.get("ok"):
        raise ValueError("strict active-chain topology failed: " + "; ".join(info.get("errors") or [str(info.get("status"))]))
    return info


def public_resume_leaf_info(info: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if info is None:
        return None
    public = copy.deepcopy(info)
    public.pop("lastPromptTemplate", None)
    active_indexes = public.pop("activeChainIndexes", [])
    active_uuids = public.pop("activeChainUuids", [])
    public["activeChainRecordCount"] = len(active_indexes)
    public["activeChainLinesDigest"] = stable_digest(",".join(str(int(idx) + 1) for idx in active_indexes))
    public["activeChainUuidsDigest"] = stable_digest(",".join(str(uid) for uid in active_uuids))
    return public


def choose_resume_leaf(records: Sequence[JsonObj]) -> Optional[str]:
    info = choose_resume_leaf_info(records)
    return info.get("selectedLeafUuid") if info.get("ok") else None


def active_chain_records(records: Sequence[JsonObj]) -> List[JsonObj]:
    info = choose_resume_leaf_info(records)
    if not info.get("ok"):
        return []
    return [records[idx] for idx in info.get("activeChainIndexes") or []]


def select_recent_file_history_snapshot_indexes(
    records: Sequence[JsonObj],
    kept_indexes: Sequence[int],
    max_snapshots: int,
) -> List[int]:
    """Keep recent file rewind checkpoints without making them live messages.

    Claude file-history snapshots commonly have no uuid/parentUuid, so they do
    not belong to the resume active chain. Keeping a bounded recent slice as
    side records preserves rewind evidence while avoiding a large Messages chain.
    """
    if max_snapshots <= 0 or not kept_indexes:
        return []
    ordered_kept = sorted(kept_indexes)
    window_start = ordered_kept[0]
    window_end = ordered_kept[-1]
    window_stop = len(records)
    for idx in range(window_end + 1, len(records)):
        if records[idx].get("type") == "last-prompt":
            window_stop = idx
            break
    else:
        window_stop = min(len(records), window_end + 41)
    selected: List[int] = []
    for idx in range(window_start, window_stop):
        obj = records[idx]
        if obj.get("type") != "file-history-snapshot":
            continue
        # Only preserve unchained snapshots here. Chained records require normal
        # parent repair and should be handled by the active chain itself.
        if obj.get("uuid") is not None or obj.get("parentUuid") is not None:
            continue
        selected.append(idx)
    return selected[-max_snapshots:]


def _record_correlation_ids(obj: JsonObj) -> set:
    values: set = set()
    for key in ("uuid", "messageId", "snapshotMessageId", "sourceUuid", "sourceUUID", "sourceToolAssistantUUID", "promptId"):
        value = obj.get(key)
        if isinstance(value, str) and value:
            values.add(value)
    msg_id = message_id(obj)
    if msg_id:
        values.add(msg_id)
    return values


def select_active_correlated_snapshot_indexes(
    records: Sequence[JsonObj],
    active_indexes: Sequence[int],
    max_snapshots: int,
    authority_index: Optional[int] = None,
) -> List[int]:
    if max_snapshots <= 0:
        return []
    active_ids: set = set()
    active_sessions: set = set()
    for idx in active_indexes:
        active_ids.update(_record_correlation_ids(records[idx]))
        session_id = records[idx].get("sessionId")
        if isinstance(session_id, str):
            active_sessions.add(session_id)
    selected: List[int] = []
    authority_stop = len(records) if authority_index is None else max(0, min(len(records), authority_index))
    for idx, obj in enumerate(records[:authority_stop]):
        if (
            obj.get("type") != "file-history-snapshot"
            or obj.get("uuid") is not None
            or obj.get("parentUuid") is not None
        ):
            continue
        snapshot_ids = _record_correlation_ids(obj)
        session_id = obj.get("sessionId")
        session_ok = not isinstance(session_id, str) or not active_sessions or session_id in active_sessions
        if session_ok and snapshot_ids.intersection(active_ids):
            selected.append(idx)
    return selected[-max_snapshots:]


def select_control_projection_indexes(records: Sequence[JsonObj]) -> List[int]:
    first_uuid_index = next((idx for idx, obj in enumerate(records) if isinstance(obj.get("uuid"), str)), len(records))
    ui_types = {"mode", "permission-mode", "custom-title", "ai-title", "agent-name"}
    selected = [
        idx for idx, obj in enumerate(records[:first_uuid_index])
        if obj.get("type") in ui_types and "uuid" not in obj
    ]
    selected.extend(idx for idx, obj in enumerate(records) if obj.get("type") == "last-prompt")
    return sorted(set(selected))


def choose_active_chain_preservation(
    records: Sequence[JsonObj],
    raw_lines: Sequence[str],
    input_bytes: int,
    target_ratio: float,
    min_recent_records: int,
    summary_budget_bytes: int,
    max_post_prompt_extension: int,
    max_file_history_snapshots: int,
    checkpoint_policy: str = "active-correlated",
    resume_leaf_override: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    resume_leaf_info = require_resume_leaf_info(
        records,
        max_post_prompt_extension=max_post_prompt_extension,
        resume_leaf_override=resume_leaf_override,
    )
    leaf = resume_leaf_info.get("selectedLeafUuid")
    chain_indexes = list(resume_leaf_info.get("activeChainIndexes") or [])
    chain = [records[idx] for idx in chain_indexes]
    if not chain:
        return None
    chain_pairs = list(zip(chain_indexes, chain))
    if not chain_pairs:
        return None

    chain_records = [obj for _, obj in chain_pairs]
    chain_raw_lines = [raw_lines[idx] for idx, _ in chain_pairs]
    target_bytes = max(4096, int(input_bytes * target_ratio))
    recent_budget = max(4096, target_bytes - summary_budget_bytes)
    chain_bytes = sum(byte_len(line) for line in chain_raw_lines)
    if chain_bytes <= recent_budget:
        chain_start = 0
    else:
        chain_start = choose_recent_start(
            chain_records,
            chain_raw_lines,
            input_bytes,
            target_ratio,
            min_recent_records,
            summary_budget_bytes,
        )
    chain_start = adjust_recent_start_for_tool_pairs(chain_records, chain_start)
    prior_compact_positions = [
        idx
        for idx, obj in enumerate(chain_records)
        if (obj.get("type") == "system" and obj.get("subtype") == "compact_boundary") or obj.get("isCompactSummary") is True
    ]
    prior_compact_record_count = len(prior_compact_positions)
    prior_compact_last_position = max(prior_compact_positions) if prior_compact_positions else None
    if prior_compact_last_position is not None and chain_start <= prior_compact_last_position:
        chain_start = prior_compact_last_position + 1
        if chain_start >= len(chain_records):
            raise ValueError("active chain has no raw records after prior compact summary; refusing to stack compact summaries")
    session_lineage_compatibility = bool(resume_leaf_info.get("sessionLineageCompatibility"))
    session_lineage_forced_start = False
    if session_lineage_compatibility:
        lineage_start = int(resume_leaf_info.get("currentSessionStartPosition") or 0)
        forced_start = max(chain_start, lineage_start)
        session_lineage_forced_start = forced_start != chain_start
        adjusted_lineage_start = adjust_recent_start_for_tool_pairs(chain_records, forced_start)
        if adjusted_lineage_start < lineage_start:
            raise ValueError(
                "tool relationship crosses session lineage transition; refusing to retain a cross-session raw suffix"
            )
        chain_start = adjusted_lineage_start
    summary_pairs = chain_pairs[:chain_start]
    kept_pairs = chain_pairs[chain_start:]
    summary_indexes = [idx for idx, _ in summary_pairs]
    kept_indexes = [idx for idx, _ in kept_pairs]
    if checkpoint_policy == "active-correlated":
        file_history_snapshot_indexes = select_active_correlated_snapshot_indexes(
            records,
            kept_indexes,
            max_file_history_snapshots,
            authority_index=resume_leaf_info.get("lastPromptIndex"),
        )
    elif checkpoint_policy == "preserve-recent":
        raise ValueError(
            "checkpoint policy preserve-recent is not available in strict active-chain mode; "
            "use active-correlated, none, or explicit physical-tail compatibility mode"
        )
    elif checkpoint_policy == "none":
        file_history_snapshot_indexes = []
    else:
        raise ValueError(f"unknown checkpoint policy: {checkpoint_policy}")
    control_projection_indexes = select_control_projection_indexes(records)
    active_index_set = set(chain_indexes)
    assigned = set(summary_indexes) | set(kept_indexes) | set(file_history_snapshot_indexes) | set(control_projection_indexes)
    excluded_branch_indexes = [
        idx for idx, obj in enumerate(records)
        if isinstance(obj.get("uuid"), str) and idx not in active_index_set
    ]
    assigned.update(excluded_branch_indexes)
    excluded_unattributed_indexes = [idx for idx in range(len(records)) if idx not in assigned]
    partition_sets = [
        set(summary_indexes), set(kept_indexes), set(file_history_snapshot_indexes),
        set(control_projection_indexes), set(excluded_branch_indexes), set(excluded_unattributed_indexes),
    ]
    if set().union(*partition_sets) != set(range(len(records))) or sum(len(x) for x in partition_sets) != len(records):
        raise AssertionError("resume topology index partition is not complete and mutually exclusive")
    return {
        "mode": "active-chain-manual-override" if resume_leaf_info.get("manualOverride") else "active-chain",
        "leafUuid": leaf,
        "resumeLeafInfo": resume_leaf_info,
        "sourceActiveChainLength": len(chain_pairs),
        "activeChainStartPosition": chain_start + 1,
        "priorCompactRecordCountInActiveChain": prior_compact_record_count,
        "priorCompactLastPositionInActiveChain": (prior_compact_last_position + 1) if prior_compact_last_position is not None else None,
        "sessionLineageCompatibility": session_lineage_compatibility,
        "sessionLineageTransitionCount": int(resume_leaf_info.get("sessionLineageTransitionCount") or 0),
        "sessionLineageForcedStart": session_lineage_forced_start,
        "currentSessionStartPosition": int(resume_leaf_info.get("currentSessionStartPosition") or 0) + 1,
        "summaryIndexes": summary_indexes,
        "rawKeepIndexes": kept_indexes,
        "sideKeepIndexes": file_history_snapshot_indexes,
        "controlProjectionIndexes": control_projection_indexes,
        "excludedBranchIndexes": excluded_branch_indexes,
        "excludedUnattributedIndexes": excluded_unattributed_indexes,
        "keptIndexes": kept_indexes,
        "fileHistorySnapshotIndexes": file_history_snapshot_indexes,
        "checkpointPolicy": checkpoint_policy,
        "omittedIndexes": summary_indexes,
        "kept": [obj for _, obj in kept_pairs],
        "fileHistorySnapshots": [records[idx] for idx in file_history_snapshot_indexes],
        "omitted": [records[idx] for idx in summary_indexes],
        "summarySource": [records[idx] for idx in summary_indexes],
        "controlProjectionRecords": [records[idx] for idx in control_projection_indexes],
        "excludedBranches": [records[idx] for idx in excluded_branch_indexes],
        "lastPromptTemplate": resume_leaf_info.get("lastPromptTemplate"),
        "recentStartRecord": min(kept_indexes) + 1 if kept_indexes else None,
        "recentEndRecord": max(kept_indexes) + 1 if kept_indexes else None,
    }


def merge_assistant_fragments(api_records: Sequence[JsonObj]) -> List[JsonObj]:
    merged: List[JsonObj] = []
    for obj in api_records:
        if (
            merged
            and api_role(obj) == "assistant"
            and api_role(merged[-1]) == "assistant"
            and message_id(obj) is not None
            and message_id(obj) == message_id(merged[-1])
        ):
            target = copy.deepcopy(merged[-1])
            target_msg = target.get("message")
            obj_msg = obj.get("message")
            if isinstance(target_msg, dict) and isinstance(obj_msg, dict):
                target_blocks = content_blocks(target)
                obj_blocks = content_blocks(obj)
                target_msg["content"] = target_blocks + obj_blocks
                if isinstance(obj.get("uuid"), str):
                    target["uuid"] = obj.get("uuid")
                merged_lines = list(target.get("_mergedLines", []))
                if not merged_lines:
                    merged_lines.append(target.get("_line"))
                merged_lines.append(obj.get("_line"))
                target["_mergedLines"] = merged_lines
                merged_uuids = list(target.get("_mergedUuids", []))
                if not merged_uuids and isinstance(merged[-1].get("uuid"), str):
                    merged_uuids.append(merged[-1].get("uuid"))
                if isinstance(obj.get("uuid"), str):
                    merged_uuids.append(obj.get("uuid"))
                if merged_uuids:
                    target["_mergedUuids"] = merged_uuids
                merged[-1] = target
            continue
        merged.append(obj)
    return merged


def merge_split_tool_result_users(api_records: Sequence[JsonObj]) -> List[JsonObj]:
    """Merge split tool_result user records for validation only.

    Claude Code may serialize one API user message as multiple JSONL `user`
    records, especially when an assistant message contains several `tool_use`
    blocks and hooks/attachments are written between results. The output JSONL
    should preserve those raw records, but the validator must reason about the
    combined API-level user message.
    """
    merged: List[JsonObj] = []
    i = 0
    while i < len(api_records):
        obj = api_records[i]
        if api_role(obj) != "user" or not tool_result_ids(obj):
            merged.append(obj)
            i += 1
            continue

        source_uuid = source_tool_assistant_uuid(obj)
        group = [obj]
        combined_ids = list(tool_result_ids(obj))
        j = i + 1
        while j < len(api_records):
            nxt = api_records[j]
            if api_role(nxt) != "user":
                break
            next_ids = tool_result_ids(nxt)
            if not next_ids:
                break
            next_source_uuid = source_tool_assistant_uuid(nxt)
            if source_uuid or next_source_uuid:
                if source_uuid != next_source_uuid:
                    break
            group.append(nxt)
            combined_ids.extend(next_ids)
            j += 1

        if len(group) == 1:
            merged.append(obj)
            i += 1
            continue

        combined = copy.deepcopy(group[0])
        combined_msg = combined.get("message")
        if isinstance(combined_msg, dict):
            blocks: List[Any] = []
            merged_lines: List[Any] = []
            merged_uuids: List[str] = []
            for user_obj in group:
                blocks.extend(content_blocks(user_obj))
                merged_lines.append(user_obj.get("_line"))
                if isinstance(user_obj.get("uuid"), str):
                    merged_uuids.append(user_obj.get("uuid"))
            combined_msg["content"] = blocks
            last_user = group[-1]
            if isinstance(last_user.get("uuid"), str):
                combined["uuid"] = last_user.get("uuid")
            combined["_mergedLines"] = merged_lines
            if merged_uuids:
                combined["_mergedUuids"] = merged_uuids
        merged.append(combined)
        i = j
    return merged


def active_api_messages_for_validation(records: Sequence[JsonObj]) -> List[Tuple[int, JsonObj]]:
    api_records: List[JsonObj] = []
    for idx, obj in enumerate(active_chain_records(records), 1):
        if not is_api_message(obj):
            continue
        clone = obj if "_line" in obj else {**obj, "_line": idx}
        api_records.append(clone)
    merged = merge_split_tool_result_users(merge_assistant_fragments(api_records))
    return [(int(obj.get("_line") or idx), obj) for idx, obj in enumerate(merged, 1)]


def adjust_recent_start_for_tool_pairs(records: Sequence[JsonObj], start: int) -> int:
    if start <= 0 or start >= len(records):
        return start
    uuid_to_index = {obj.get("uuid"): idx for idx, obj in enumerate(records) if isinstance(obj.get("uuid"), str)}
    tool_use_to_assistant: Dict[str, int] = {}
    for idx, obj in enumerate(records):
        for tool_id in tool_use_ids(obj):
            tool_use_to_assistant[tool_id] = idx
    api_indexes = [idx for idx, obj in enumerate(records) if is_api_message(obj)]
    if not api_indexes:
        return start
    prev_api_by_index: Dict[int, Optional[int]] = {}
    prev: Optional[int] = None
    for idx in api_indexes:
        prev_api_by_index[idx] = prev
        prev = idx

    adjusted = start
    changed = True
    while changed:
        changed = False
        first_kept = records[adjusted] if 0 <= adjusted < len(records) else None
        if isinstance(first_kept, dict) and first_kept.get("type") == "attachment":
            att = first_kept.get("attachment")
            tool_id = att.get("toolUseID") if isinstance(att, dict) else None
            source_idx = tool_use_to_assistant.get(tool_id) if isinstance(tool_id, str) else None
            if source_idx is not None and source_idx < adjusted:
                adjusted = source_idx
                changed = True
                continue
        first_api = next((idx for idx in api_indexes if idx >= adjusted), None)
        if first_api is None:
            return adjusted
        first = records[first_api]
        first_results = tool_result_ids(first)
        prev_api = prev_api_by_index.get(first_api)
        if api_role(first) == "assistant" and message_id(first) is not None:
            fragment_start = first_api
            fragment_prev = prev_api
            while (
                fragment_prev is not None
                and api_role(records[fragment_prev]) == "assistant"
                and message_id(records[fragment_prev]) == message_id(first)
            ):
                fragment_start = fragment_prev
                fragment_prev = prev_api_by_index.get(fragment_prev)
            if fragment_start < adjusted:
                adjusted = fragment_start
                changed = True
                continue
        if first_results:
            source_uuid = first.get("sourceToolAssistantUUID")
            source_idx = uuid_to_index.get(source_uuid) if isinstance(source_uuid, str) else None
            if source_idx is None:
                source_idx = min((tool_use_to_assistant[x] for x in first_results if x in tool_use_to_assistant), default=None)
            if source_idx is not None and source_idx < adjusted:
                new_adjusted = source_idx
            else:
                prev_uses = tool_use_ids(records[prev_api]) if prev_api is not None else []
                if prev_api is None or api_role(records[prev_api]) != "assistant" or prev_uses != first_results:
                    raise ValueError(
                        "recent cut begins with an orphan tool_result whose source tool_use cannot be resolved"
                    )
                else:
                    new_adjusted = min(adjusted, prev_api)
            if new_adjusted >= adjusted:
                raise ValueError("tool-pair cut adjustment did not move monotonically toward the source tool_use")
            adjusted = new_adjusted
            changed = True
            continue
        if api_role(first) == "assistant" and tool_use_ids(first):
            next_api = next((idx for idx in api_indexes if idx > first_api), None)
            if next_api is not None and next_api < adjusted:
                adjusted = next_api
                changed = True
    return adjusted


def load_json_file(path: pathlib.Path) -> Any:
    with path.open("r", encoding="utf-8-sig") as f:
        return json.load(f)


def skill_root() -> pathlib.Path:
    return pathlib.Path(__file__).resolve().parents[1]


def configure_summary_resources(
    importance_words_path: Optional[pathlib.Path] = None,
    topic_patterns_path: Optional[pathlib.Path] = None,
    summary_template_path: Optional[pathlib.Path] = None,
    strict: bool = False,
) -> None:
    """Load optional summary rules from the skill's config directory.

    Explicit paths are strict by default from the caller's perspective. Default
    package resources are best-effort so the compressor can still run from a
    copied single script.
    """
    global IMPORTANT_WORDS, TOPIC_MEMORY_PATTERNS, _ACTIVE_SUMMARY_TEMPLATE_PATH, _SUMMARY_RESOURCES_CONFIGURED

    root = skill_root()
    imp_path = importance_words_path or (root / "config" / "importance_words.json")
    topic_path = topic_patterns_path or (root / "config" / "topic_patterns.json")
    template_path = summary_template_path or (root / "templates" / "summary_template_en.md")

    def explicit(path_value: Optional[pathlib.Path]) -> bool:
        return path_value is not None

    if imp_path.exists():
        try:
            data = load_json_file(imp_path)
            words = data.get("importance_words") if isinstance(data, dict) else data
            if not isinstance(words, list) or not all(isinstance(x, str) for x in words):
                raise ValueError("importance words config must be a string array or an object with importance_words")
            IMPORTANT_WORDS = tuple(dict.fromkeys(x for x in words if x.strip()))
        except Exception:
            if strict or explicit(importance_words_path):
                raise
            IMPORTANT_WORDS = DEFAULT_IMPORTANCE_WORDS
    elif strict or explicit(importance_words_path):
        raise FileNotFoundError(f"importance words config not found: {imp_path}")
    else:
        IMPORTANT_WORDS = DEFAULT_IMPORTANCE_WORDS

    if topic_path.exists():
        try:
            data = load_json_file(topic_path)
            topics = data.get("topics") if isinstance(data, dict) else data
            if not isinstance(topics, list):
                raise ValueError("topic patterns config must be an array or an object with topics")
            parsed = []
            for item in topics:
                if not isinstance(item, dict):
                    raise ValueError("each topic pattern must be an object")
                name = item.get("name")
                needles = item.get("needles")
                if not isinstance(name, str) or not isinstance(needles, list) or not all(isinstance(x, str) for x in needles):
                    raise ValueError("each topic pattern needs name and string-array needles")
                parsed.append((name, tuple(x for x in needles if x.strip())))
            TOPIC_MEMORY_PATTERNS = tuple(parsed) if parsed else DEFAULT_TOPIC_MEMORY_PATTERNS
        except Exception:
            if strict or explicit(topic_patterns_path):
                raise
            TOPIC_MEMORY_PATTERNS = DEFAULT_TOPIC_MEMORY_PATTERNS
    elif strict or explicit(topic_patterns_path):
        raise FileNotFoundError(f"topic patterns config not found: {topic_path}")
    else:
        TOPIC_MEMORY_PATTERNS = DEFAULT_TOPIC_MEMORY_PATTERNS

    if template_path.exists():
        _ACTIVE_SUMMARY_TEMPLATE_PATH = template_path
    elif strict or explicit(summary_template_path):
        raise FileNotFoundError(f"summary template not found: {template_path}")
    else:
        _ACTIVE_SUMMARY_TEMPLATE_PATH = None
    _SUMMARY_RESOURCES_CONFIGURED = True


def ensure_summary_resources() -> None:
    if not _SUMMARY_RESOURCES_CONFIGURED:
        configure_summary_resources(strict=False)


def split_ranges(n: int) -> Tuple[range, range]:
    early_end = int(n * 0.5)
    return range(0, early_end), range(early_end, n)


def get_role(obj: JsonObj) -> str:
    msg = obj.get("message")
    if isinstance(msg, dict) and msg.get("role"):
        return str(msg.get("role"))
    return str(obj.get("type", ""))


def text_has_any(text: str, needles: Iterable[str]) -> bool:
    hay = text.lower()
    return any(n.lower() in hay for n in needles if n)


def text_script_groups(text: str) -> List[str]:
    groups: set = set()
    for ch in text:
        cp = ord(ch)
        if 0x0600 <= cp <= 0x06FF or 0x0750 <= cp <= 0x077F:
            groups.add("arabic-script")
        elif 0x0370 <= cp <= 0x03FF or 0x1F00 <= cp <= 0x1FFF:
            groups.add("greek-script")
        elif 0x0530 <= cp <= 0x058F:
            groups.add("armenian-script")
        elif 0x0590 <= cp <= 0x05FF or 0xFB1D <= cp <= 0xFB4F:
            groups.add("hebrew-script")
        elif 0x0400 <= cp <= 0x052F:
            groups.add("cyrillic-script")
        elif 0x0900 <= cp <= 0x097F:
            groups.add("devanagari-script")
        elif 0x0980 <= cp <= 0x09FF:
            groups.add("bengali-script")
        elif 0x0B80 <= cp <= 0x0BFF:
            groups.add("tamil-script")
        elif 0x0C00 <= cp <= 0x0C7F:
            groups.add("telugu-script")
        elif 0x0D00 <= cp <= 0x0D7F:
            groups.add("malayalam-script")
        elif 0x0E00 <= cp <= 0x0E7F:
            groups.add("thai-script")
        elif 0x3040 <= cp <= 0x30FF or 0x31F0 <= cp <= 0x31FF:
            groups.add("japanese-script")
        elif 0xAC00 <= cp <= 0xD7AF or 0x1100 <= cp <= 0x11FF:
            groups.add("korean-script")
        elif 0x10A0 <= cp <= 0x10FF or 0x2D00 <= cp <= 0x2D2F:
            groups.add("georgian-script")
        elif 0x1200 <= cp <= 0x137F:
            groups.add("ethiopic-script")
        elif 0x3400 <= cp <= 0x4DBF or 0x4E00 <= cp <= 0x9FFF:
            groups.add("han-script")
    return sorted(groups)


def assistant_decision_language_groups(text: str) -> List[str]:
    hay = text.casefold()
    groups = [
        language
        for language, terms in ASSISTANT_DECISION_LANGUAGE_TERMS.items()
        if any(term.casefold() in hay for term in terms)
    ]
    if groups:
        return sorted(set(groups))
    return text_script_groups(text)


def multilingual_structural_decision_score(text: str) -> int:
    letters = sum(1 for ch in text if unicodedata.category(ch).startswith("L"))
    if letters < 40:
        return 0
    sentence_marks = sum(text.count(mark) for mark in (".", "?", "!", "。", "？", "！", "؛", "۔"))
    structural_marks = sum(text.count(mark) for mark in ("\n", ":", "：", ";", "；", "- ", "•"))
    paragraph_count = len([part for part in re.split(r"\n\s*\n", text) if part.strip()])
    score = 0
    if sentence_marks >= 2:
        score += 2
    if structural_marks >= 2 or paragraph_count >= 2:
        score += 2
    if len(text) >= 180:
        score += 2
    if len(text_script_groups(text)) >= 1 and len(text) >= 120:
        score += 1
    return score


def assistant_research_decision_score(text: str) -> int:
    if not text or is_noisy_text(text):
        return 0
    hay = text.lower()
    high_hits = sum(1 for word in ASSISTANT_HIGH_VALUE_DECISION_WORDS if word and word.lower() in hay)
    decision_hits = sum(1 for word in ASSISTANT_RESEARCH_DECISION_WORDS if word and word.lower() in hay)
    action_hits = sum(1 for word in ASSISTANT_RESEARCH_ACTION_WORDS if word and word.lower() in hay)
    score = high_hits * 8 + decision_hits * 3
    # Action phrases are weak evidence by themselves; they only become important
    # when paired with an actual decision/reason/evidence signal.
    if decision_hits or high_hits:
        score += min(action_hits, 4)
    if decision_hits and action_hits:
        score += 4
    if re.search(r"\b(therefore|because|rationale|conclusion|verdict|decision)\b", hay):
        score += 3
    if any(word in text for word in ("\u56e0\u4e3a", "\u6240\u4ee5", "\u7ed3\u8bba", "\u5224\u65ad", "\u88c1\u65ad", "\u7406\u7531")):
        score += 3
    folded = text.casefold()
    language_term_hits = max(
        (
            sum(1 for term in terms if term.casefold() in folded)
            for terms in ASSISTANT_DECISION_LANGUAGE_TERMS.values()
        ),
        default=0,
    )
    if language_term_hits:
        score += min(12, language_term_hits * 3)
    score += multilingual_structural_decision_score(text)
    return score


def is_assistant_research_decision(obj: JsonObj, text: Optional[str] = None) -> bool:
    if obj.get("type") != "assistant":
        return False
    txt = record_text(obj) if text is None else text
    return assistant_research_decision_score(txt) >= 6


def collect_summary_inputs(records: Sequence[JsonObj]) -> Dict[str, Any]:
    ensure_summary_resources()
    type_counts = collections.Counter(obj.get("type", "<missing>") for obj in records)
    subtype_counts = collections.Counter(
        f"{obj.get('type')}:{obj.get('subtype')}" for obj in records if obj.get("subtype")
    )
    session_counts = collections.Counter(obj.get("sessionId", "<missing>") for obj in records)
    cwd_counts = collections.Counter(str(obj.get("cwd")) for obj in records if obj.get("cwd"))
    versions = collections.Counter(str(obj.get("version")) for obj in records if obj.get("version"))
    tools = collections.Counter()
    paths = collections.Counter()
    user_items: List[Tuple[int, str]] = []
    human_user_items: List[Tuple[int, str]] = []
    tool_result_items: List[Tuple[int, str]] = []
    assistant_items: List[Tuple[int, str]] = []
    assistant_decision_items: List[Tuple[int, str]] = []
    compact_items: List[Tuple[int, str]] = []
    compact_boundary_items: List[Tuple[int, str]] = []
    errors: List[Tuple[int, str]] = []
    file_history = 0
    attachments = collections.Counter()
    topic_memory = {name: [] for name, _ in TOPIC_MEMORY_PATTERNS}

    for idx, obj in enumerate(records, 1):
        txt = record_text(obj)
        noisy = is_noisy_text(txt)
        semantic_txt = semantic_message_text(obj)
        if not noisy:
            for path in extract_paths(txt):
                if not is_noisy_text(path):
                    paths[path] += 1
        if obj.get("isCompactSummary"):
            compact_items.append((idx, truncate(txt.strip(), 2400)))
        if obj.get("type") == "system" and obj.get("subtype") == "compact_boundary":
            meta = obj.get("compactMetadata") if isinstance(obj.get("compactMetadata"), dict) else {}
            compact_boundary_items.append(
                (
                    idx,
                    one_line(
                        f"uuid={obj.get('uuid')} preserveMode={meta.get('preserveMode')} "
                        f"selectedLeaf={meta.get('selectedLeafUuid')} "
                        f"recent={meta.get('recentRecordStart')}-{meta.get('recentRecordEnd')} "
                        f"sourceActiveChainLength={meta.get('sourceActiveChainLength')} "
                        f"postLastPromptExtensionRecords={((meta.get('resumeLeafInfo') or {}).get('postLastPromptExtensionRecords') if isinstance(meta.get('resumeLeafInfo'), dict) else None)}",
                        800,
                    ),
                )
            )
        if obj.get("type") == "assistant":
            msg = obj.get("message")
            if isinstance(msg, dict):
                content = msg.get("content")
                if isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "tool_use":
                            tools[str(block.get("name", "tool"))] += 1
            if semantic_txt:
                assistant_items.append((idx, one_line(semantic_txt, 520)))
            if semantic_txt and is_assistant_research_decision(obj, semantic_txt):
                assistant_decision_items.append((idx, one_line(semantic_txt, 900)))
        elif obj.get("type") == "user":
            if is_human_user_record(obj) and semantic_txt:
                is_important = text_has_any(semantic_txt, IMPORTANT_WORDS)
                human_user_items.append((idx, truncate(semantic_txt.strip(), 2800 if is_important else 1600)))
                user_items.append((idx, one_line(semantic_txt, 700 if is_important else 420)))
            elif txt and not noisy:
                is_important = text_has_any(txt, IMPORTANT_WORDS)
                if is_tool_result_user_record(obj):
                    tool_result_items.append((idx, one_line(txt, 600)))
                user_items.append((idx, one_line(txt, 700 if is_important else 420)))
        elif obj.get("type") == "system":
            if obj.get("subtype") == "api_error" or obj.get("error"):
                errors.append((idx, one_line(txt or json.dumps(obj, ensure_ascii=False), 520)))
        elif obj.get("type") == "attachment":
            att = obj.get("attachment")
            if isinstance(att, dict):
                attachments[str(att.get("type", "<unknown>"))] += 1
                if att.get("hookName"):
                    attachments[f"hook:{att.get('hookName')}"] += 1
        elif obj.get("type") == "file-history-snapshot":
            file_history += 1
        if txt and not noisy:
            for name, needles in TOPIC_MEMORY_PATTERNS:
                if text_has_any(txt, needles):
                    topic_memory[name].append((idx, one_line(txt, 850)))

    important_user = [item for item in user_items if text_has_any(item[1], IMPORTANT_WORDS)]
    normal_user = [item for item in user_items if item not in important_user]
    user_kept = sorted(
        temporal_sample_items(normal_user, 30) + temporal_sample_items(important_user, 120),
        key=lambda item: item[0],
    )

    return {
        "type_counts": type_counts,
        "subtype_counts": subtype_counts,
        "session_counts": session_counts,
        "cwd_counts": cwd_counts,
        "versions": versions,
        "tools": tools,
        "paths": paths,
        "user_items": temporal_sample_items(user_kept, 150),
        "human_user_items": temporal_sample_items(human_user_items, 150),
        "tool_result_items": temporal_sample_items(tool_result_items, 70),
        "assistant_items": temporal_sample_items(assistant_items, 100),
        "assistant_decision_items": temporal_sample_items(assistant_decision_items, 120),
        "compact_items": temporal_sample_items(compact_items, 25),
        "compact_boundary_items": temporal_sample_items(compact_boundary_items, 25),
        "errors": temporal_sample_items(errors, 35),
        "file_history": file_history,
        "attachments": attachments,
        "topic_memory": topic_memory,
    }


def temporal_sample_items(items: Sequence[Tuple[int, str]], limit: int) -> List[Tuple[int, str]]:
    ordered = list(items)
    if limit <= 0:
        return []
    if len(ordered) <= limit:
        return ordered
    early_count = max(1, limit // 4)
    late_count = max(1, limit * 2 // 5)
    middle_count = max(0, limit - early_count - late_count)
    chosen = ordered[:early_count] + ordered[-late_count:]
    middle_pool = ordered[early_count:len(ordered) - late_count]
    if middle_count and middle_pool:
        if middle_count >= len(middle_pool):
            chosen.extend(middle_pool)
        else:
            for pos in range(middle_count):
                pool_index = ((pos + 1) * (len(middle_pool) + 1)) // (middle_count + 1) - 1
                chosen.append(middle_pool[max(0, min(len(middle_pool) - 1, pool_index))])
    return sorted(dict((item[0], item) for item in chosen).values(), key=lambda item: item[0])[:limit]


def fmt_counter(counter: collections.Counter, limit: int = 12) -> str:
    if not counter:
        return "none observed"
    return "; ".join(f"{k}={v}" for k, v in counter.most_common(limit))


def fmt_items(items: Sequence[Tuple[int, str]], limit: int, empty: str = "none observed") -> str:
    if not items:
        return empty
    lines = []
    selected = temporal_sample_items(items, limit)
    for idx, text in selected:
        lines.append(f"- L{idx}: {text}")
    more = len(items) - limit
    if more > 0:
        lines.append(f"- {more} additional similar items were counted but not expanded.")
    return "\n".join(lines)


def fmt_topic_memory(topic_memory: Dict[str, List[Tuple[int, str]]], per_topic: int = 6) -> str:
    lines: List[str] = []
    for name, items in topic_memory.items():
        lines.append(f"### {name}")
        if not items:
            lines.append("No direct hit in the summarized range.")
            continue
        for idx, text in temporal_sample_items(items, per_topic):
            lines.append(f"- L{idx}: {text}")
    return "\n".join(lines)


def infer_long_term_memory(human_items: Sequence[Tuple[int, str]], all_info: Dict[str, Any]) -> str:
    lines = [
        "- This ledger is extracted from the summarized range by generic rules. It contains no project facts built into the skill.",
        "- For humanities, legal, art, strategy, planning, history, feasibility, and document-research sessions, preserve timeline, user wording, final decisions, rejected alternatives, evidence provenance, risk judgments, and unresolved questions.",
        "- If the same topic changed over time, later work should judge by event order instead of treating early states as final.",
        "- Recent raw records remain in this candidate JSONL for rewind. Exact early/middle wording requires the original JSONL or archive.",
        "",
        "### Extracted human-user prompts from summarized records",
        fmt_items(human_items, 35),
        "",
        "### Assistant research decisions and rationales from summarized records",
        fmt_items(
            all_info.get("assistant_decision_items", []),
            35,
            "No assistant research-decision records were extracted by generic rules.",
        ),
        "",
        "### Topic evidence index",
        fmt_topic_memory(all_info["topic_memory"], 6),
    ]
    return "\n".join(lines)


class SafeFormatDict(dict):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def default_summary_template() -> str:
    return """# Codex Offline Compression Summary

This is a candidate Claude Code JSONL compact summary generated outside Claude. It summarizes only older records from the selected active chain. Rewound, inactive, and unattributed records are excluded.

## 1. Scope

- Source file label: {input_path}
- Original record count: {total_records}
- Active-chain records selected for summary: {omitted_record_count} records before the preserved active-chain window
- Recent raw active-chain records preserved: {recent_record_count} records
- Physical line window of preserved records: {recent_start} to {recent_end}
- Time span summarized: {first_ts} to {last_omitted_ts}
- Time span preserved: {first_kept_ts} to {last_kept_ts}
- Session distribution: {session_counts}
- Common working directories: {cwd_counts}
- Claude Code versions: {version_counts}

## 2. Structural Overview

- Record types: {type_counts}
- System subtypes: {subtype_counts}
- Tool invocation overview: {tool_counts}
- Attachment / hook overview: {attachment_counts}
- File history snapshots: {file_history_count}
- Existing compact summaries summarized into this layer: {existing_compact_count}
- Human user prompts: {human_user_count}
- Tool-result user records: {tool_result_user_count}

## 3. Long-Term Memory Ledger

{long_term_memory}

## 4. Early / Middle Summary

### 4.1 Early
{early_summary}

### 4.2 Middle
{middle_summary}

## 5. Assistant Behavior and Evidence

### 5.1 Assistant research decisions and rationales
{assistant_decision_items}

### 5.2 Key assistant outputs
{assistant_items}

### 5.3 Key paths and filenames
{path_counts}

### 5.4 Errors and anomalies
{error_section}

## 6. Existing Compact Records

### 6.1 compact_boundary layer
{compact_boundary_items}

### 6.2 isCompactSummary layer
{compact_items}

### 6.3 Repeated compression policy
- Treat previous compact layers as prior memory, not as live stacked context.
- Fold still-relevant facts into the current compact summary.
- Keep provenance, hashes, file labels, and line ranges in metadata or sidecars.
- If prior layers themselves are too large, switch to a long-term memory ledger.

## 7. Recent Raw Preservation

{recent_preservation_notes}

## 8. Important Reminders

- Exact wording lives in the source JSONL or external archives.
- This file is a candidate transcript rewrite, not a proof of Claude runtime behavior.
- For humanities, law, art, strategy, planning, history, feasibility, and document-research sessions, preserve user goals, reasons, rejected alternatives, version changes, provenance, unresolved questions, and risk judgments.
- Project-specific facts must come from the JSONL or an explicit handoff summary, not from hardcoded skill memory.
"""


def load_summary_template() -> str:
    ensure_summary_resources()
    if _ACTIVE_SUMMARY_TEMPLATE_PATH and _ACTIVE_SUMMARY_TEMPLATE_PATH.exists():
        return _ACTIVE_SUMMARY_TEMPLATE_PATH.read_text(encoding="utf-8-sig", errors="strict")
    return default_summary_template()


def canonical_json_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256_hex(encoded)


def build_pack_request_manifest(
    *,
    target_ratio: float,
    min_recent_records: int,
    summary_char_budget: int,
    preserve_active_chain: bool,
    max_post_prompt_extension: int,
    max_file_history_snapshots: int,
    checkpoint_policy: str,
    resume_leaf_override: Optional[str],
    model_pack_char_budget: int,
    model_pack_estimated_token_budget: int,
    preserve_prior_summaries_verbatim: bool,
    target_estimated_tokens: Optional[int],
    handoff_summary_sha256: Optional[str],
) -> Tuple[Dict[str, Any], str]:
    ensure_summary_resources()
    resource_manifest = {
        "importanceWordsSha256": canonical_json_sha256(list(IMPORTANT_WORDS)),
        "topicPatternsSha256": canonical_json_sha256(
            [{"name": name, "needles": list(needles)} for name, needles in TOPIC_MEMORY_PATTERNS]
        ),
        "summaryTemplateSha256": sha256_hex(load_summary_template().encode("utf-8")),
    }
    manifest: Dict[str, Any] = {
        "schema": MODEL_PACK_SCHEMA_VERSION,
        "engine": CODEX_OFFLINE_COMPRESSION_VERSION,
        "targetRatio": target_ratio,
        "targetEstimatedTokens": target_estimated_tokens,
        "minRecentRecords": min_recent_records,
        "summaryCharBudget": summary_char_budget,
        "preserveActiveChain": bool(preserve_active_chain),
        "maxPostPromptExtension": max_post_prompt_extension,
        "maxFileHistorySnapshots": max_file_history_snapshots,
        "checkpointPolicy": checkpoint_policy,
        "resumeLeafOverride": resume_leaf_override,
        "modelPackCharBudget": model_pack_char_budget,
        "modelPackEstimatedTokenBudget": model_pack_estimated_token_budget,
        "preservePriorSummariesVerbatim": bool(preserve_prior_summaries_verbatim),
        "handoffSummarySha256": handoff_summary_sha256,
        "resources": resource_manifest,
    }
    return manifest, canonical_json_sha256(manifest)


def make_range_summary(label: str, info: Dict[str, Any]) -> str:
    return "\n".join(
        [
            f"- Record types: {fmt_counter(info['type_counts'], 14)}",
            f"- Main directories: {fmt_counter(info['cwd_counts'], 6)}",
            f"- Claude Code versions: {fmt_counter(info['versions'], 6)}",
            f"- Human user prompts:\n{fmt_items(info['human_user_items'], 24)}",
        ]
    )


def make_summary_text(
    omitted: Sequence[JsonObj],
    kept: Sequence[JsonObj],
    input_path: pathlib.Path,
    start_idx: int,
    total_records: int,
    summary_char_budget: int,
    handoff_summary_text: Optional[str] = None,
) -> str:
    require_summary_char_budget(summary_char_budget)
    ensure_summary_resources()
    early_range, middle_range = split_ranges(len(omitted))
    early = [omitted[i] for i in early_range]
    middle = [omitted[i] for i in middle_range]
    all_info = collect_summary_inputs(omitted)
    early_info = collect_summary_inputs(early)
    middle_info = collect_summary_inputs(middle)
    kept_types = collections.Counter(obj.get("type", "<missing>") for obj in kept)
    first_ts = next((obj.get("timestamp") for obj in omitted if obj.get("timestamp")), "unknown")
    last_omitted_ts = next((obj.get("timestamp") for obj in reversed(omitted) if obj.get("timestamp")), "unknown")
    first_kept_ts = next((obj.get("timestamp") for obj in kept if obj.get("timestamp")), "unknown")
    last_kept_ts = next((obj.get("timestamp") for obj in reversed(kept) if obj.get("timestamp")), "unknown")

    long_term_memory = infer_long_term_memory(all_info["human_user_items"], all_info)
    if handoff_summary_text:
        long_term_memory += "\n\n### External handoff summary supplied by user\n"
        long_term_memory += handoff_summary_text

    if all_info["errors"]:
        error_section = "Potential system/api_error samples were found. Treat repeated logs as error evidence, not new facts:\n" + fmt_items(all_info["errors"], 10)
    else:
        error_section = "No direct system/api_error records were extracted from the summarized range."

    context = SafeFormatDict(
        input_path="SOURCE_JSONL",
        total_records=total_records,
        start_idx=start_idx,
        omitted_record_count=len(omitted),
        recent_record_count=len(kept),
        recent_start=start_idx + 1 if kept else "none",
        recent_end=total_records if kept else "none",
        first_ts=first_ts,
        last_omitted_ts=last_omitted_ts,
        first_kept_ts=first_kept_ts,
        last_kept_ts=last_kept_ts,
        session_counts=fmt_counter(all_info["session_counts"], 8),
        cwd_counts=fmt_counter(all_info["cwd_counts"], 8),
        version_counts=fmt_counter(all_info["versions"], 8),
        type_counts=fmt_counter(all_info["type_counts"], 18),
        subtype_counts=fmt_counter(all_info["subtype_counts"], 18),
        tool_counts=fmt_counter(all_info["tools"], 18),
        attachment_counts=fmt_counter(all_info["attachments"], 10),
        file_history_count=all_info["file_history"],
        existing_compact_count=len(all_info["compact_items"]),
        human_user_count=len(all_info["human_user_items"]),
        tool_result_user_count=len(all_info["tool_result_items"]),
        long_term_memory=long_term_memory,
        early_summary=make_range_summary("early", early_info),
        middle_summary=make_range_summary("middle", middle_info),
        assistant_decision_items=fmt_items(
            all_info["assistant_decision_items"],
            40,
            "No assistant research-decision records were extracted by generic rules.",
        ),
        assistant_items=fmt_items(all_info["assistant_items"], 32),
        path_counts=fmt_counter(all_info["paths"], 50),
        error_section=error_section,
        compact_boundary_items=fmt_items(all_info["compact_boundary_items"], 14, "No compact_boundary records found in summarized range."),
        compact_items=fmt_items(all_info["compact_items"], 14, "No isCompactSummary records found in summarized range."),
        recent_preservation_notes=(
            f"Recent records are preserved as raw JSONL. Preserved record types: {fmt_counter(kept_types, 18)}. "
            "If a preserved record's parentUuid pointed to omitted history, the compressor performs minimal relinking inside the same session or the explicitly requested single resume chain. "
            "Cross-session parent links are not invented."
        ),
    )
    rendered = load_summary_template().format_map(context)
    if handoff_summary_text and len(rendered) > summary_char_budget:
        raise ValueError(
            "complete external handoff does not fit the deterministic summary budget; "
            "increase --summary-char-budget or use the default model-assisted workflow"
        )
    return truncate(rendered, summary_char_budget)


MODEL_SUMMARY_MARKER = "claude-jsonl-compressor:model-summary v11"


def parse_model_summary_metadata(text: str) -> Dict[str, str]:
    metadata: Dict[str, str] = {}
    match = re.match(
        r"\A<!-- " + re.escape(MODEL_SUMMARY_MARKER) + r"\r?\n(?P<body>.*?)-->(?:\r?\n|\Z)",
        text,
        re.DOTALL,
    )
    if not match:
        return metadata
    for raw_line in match.group("body").splitlines():
        line = raw_line.strip()
        if not line or ":" not in line:
            continue
        key, val = line.split(":", 1)
        metadata[key.strip()] = val.strip()
    return metadata


def model_summary_anchor_lines(text: str) -> List[int]:
    anchors: List[int] = []
    for match in re.finditer(r"(?<![A-Za-z0-9_])L(\d{1,9})(?![A-Za-z0-9_])", text):
        try:
            anchors.append(int(match.group(1)))
        except ValueError:
            continue
    return anchors


def model_summary_handoff_anchor_lines(text: str) -> List[int]:
    anchors: List[int] = []
    for match in re.finditer(r"(?<![A-Za-z0-9_])H(\d{1,9})(?![A-Za-z0-9_])", text):
        try:
            anchors.append(int(match.group(1)))
        except ValueError:
            continue
    return anchors


def model_pack_evidence_anchor_lines(pack_text: str) -> List[int]:
    marker = "## Evidence Records"
    start = pack_text.find(marker)
    if start < 0:
        return []
    start += len(marker)
    end = pack_text.find("\n## External Handoff Summary", start)
    evidence_text = pack_text[start:] if end < 0 else pack_text[start:end]
    anchors: List[int] = []
    for line in evidence_text.splitlines():
        match = re.match(r"^- L(\d{1,9}) type=", line)
        if not match:
            continue
        try:
            anchors.append(int(match.group(1)))
        except ValueError:
            continue
    return anchors


def model_pack_handoff_anchor_lines(pack_text: str) -> List[int]:
    marker = "## External Handoff Summary"
    start = pack_text.find(marker)
    if start < 0:
        return []
    anchors: List[int] = []
    for line in pack_text[start + len(marker):].splitlines():
        match = re.match(r"^- H(\d{1,9})\s", line)
        if match:
            anchors.append(int(match.group(1)))
    return anchors


def anchor_lines_digest(lines: Sequence[int]) -> str:
    unique = sorted(set(int(line) for line in lines))
    return stable_digest(",".join(str(line) for line in unique))


def anchor_groups_digest(groups: Dict[str, Sequence[int]]) -> str:
    canonical = {
        str(name): sorted(set(int(line) for line in lines))
        for name, lines in sorted(groups.items())
    }
    return stable_digest(json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def required_handoff_anchor_groups(anchor_count: int) -> Dict[str, List[int]]:
    """Require chronologically distributed H anchors without forcing verbatim output."""
    if anchor_count <= 0:
        return {}
    candidates = [
        ("handoff-early", 1),
        ("handoff-middle", max(1, (anchor_count + 1) // 2)),
        ("handoff-late", max(1, (2 * anchor_count + 2) // 3)),
        ("handoff-latest", anchor_count),
    ]
    groups: Dict[str, List[int]] = {}
    used: set = set()
    for name, anchor in candidates:
        if anchor in used:
            continue
        used.add(anchor)
        groups[name] = [anchor]
    return groups


def validate_model_summary_text(
    text: str,
    source_digest: str,
    omitted_digest: str,
    total_records: int,
    omitted_indexes: Sequence[int],
    allowed_anchor_lines: Optional[Sequence[int]] = None,
    expected_evidence_anchor_lines_digest: Optional[str] = None,
    required_anchor_groups: Optional[Dict[str, Sequence[int]]] = None,
    expected_required_anchor_groups_digest: Optional[str] = None,
    expected_handoff_summary_digest: Optional[str] = None,
    allowed_handoff_anchor_count: int = 0,
    expected_pack_request_digest: Optional[str] = None,
    required_claim_sources: Optional[Dict[str, str]] = None,
    expected_required_claim_sources_digest: Optional[str] = None,
    min_chars: int = 800,
) -> Dict[str, Any]:
    errors: List[str] = []
    warnings: List[str] = []
    stripped = text.strip()
    metadata_match = re.match(
        r"\A<!-- " + re.escape(MODEL_SUMMARY_MARKER) + r"\r?\n(?P<body>.*?)-->(?:\r?\n|\Z)",
        stripped,
        re.DOTALL,
    )
    if metadata_match is None:
        errors.append(
            f"model summary must begin with the exact HTML metadata comment for {MODEL_SUMMARY_MARKER}"
        )
        metadata: Dict[str, str] = {}
        visible_body = stripped
        metadata_duplicate_keys: List[str] = []
    else:
        metadata = {}
        metadata_duplicate_keys = []
        for raw_line in metadata_match.group("body").splitlines():
            line = raw_line.strip()
            if not line or ":" not in line:
                continue
            key, value = line.split(":", 1)
            key = key.strip()
            if key in metadata:
                metadata_duplicate_keys.append(key)
            metadata[key] = value.strip()
        visible_body = stripped[metadata_match.end():].lstrip("\r\n")
        if "<!--" in metadata_match.group("body") or "-->" in metadata_match.group("body"):
            errors.append("model summary metadata contains a nested or premature HTML comment marker")
    if metadata_duplicate_keys:
        errors.append(f"model summary metadata contains duplicate keys: {sorted(set(metadata_duplicate_keys))}")
    if metadata.get("source_sha256") != source_digest:
        errors.append("model summary source_sha256 does not match current input JSONL bytes")
    if metadata.get("summary_source_sha256") != omitted_digest:
        errors.append("model summary summary_source_sha256 does not match the active records selected for summarization")
    if expected_evidence_anchor_lines_digest is not None:
        if metadata.get("evidence_anchor_lines_digest") != expected_evidence_anchor_lines_digest:
            errors.append("model summary evidence_anchor_lines_digest does not match the generated evidence pack")
    if expected_required_anchor_groups_digest is not None:
        if metadata.get("required_anchor_groups_digest") != expected_required_anchor_groups_digest:
            errors.append("model summary required_anchor_groups_digest does not match the generated evidence pack")
    expected_handoff_value = expected_handoff_summary_digest or "none"
    if metadata.get("handoff_summary_digest") != expected_handoff_value:
        errors.append("model summary handoff_summary_digest does not match the generated evidence pack")
    if expected_pack_request_digest is not None:
        if metadata.get("pack_request_digest") != expected_pack_request_digest:
            errors.append("model summary pack_request_digest does not match the current compression request and resources")

    normalized_claim_sources: Dict[str, str] = {}
    invalid_claim_source_keys: List[str] = []
    for raw_key, raw_source in (required_claim_sources or {}).items():
        try:
            key = str(int(raw_key))
        except (TypeError, ValueError):
            invalid_claim_source_keys.append(str(raw_key))
            continue
        normalized_claim_sources[key] = str(raw_source)
    if invalid_claim_source_keys:
        errors.append(f"required claim source map has invalid line keys: {invalid_claim_source_keys[:20]}")
    actual_claim_sources_digest = canonical_json_sha256(normalized_claim_sources)
    if (
        expected_required_claim_sources_digest is not None
        and actual_claim_sources_digest != expected_required_claim_sources_digest
    ):
        errors.append("required claim source map does not match its expected digest")
    expected_claim_digest = expected_required_claim_sources_digest or actual_claim_sources_digest
    if metadata.get("required_claim_sources_digest") != expected_claim_digest:
        errors.append("model summary required_claim_sources_digest does not match the generated evidence pack")
    if len(stripped) < min_chars:
        errors.append(f"model summary is too short for reliable semantic compression: {len(stripped)} chars")
    required_headings = [
        "Current State",
        "Timeline and Supersessions",
        "Decisions and Reasons",
        "Assistant Research Decisions and Rationales",
        "Rejected or Superseded Alternatives",
        "Evidence and Source Anchors",
        "User Wording and Constraints",
        "Risks, Unknowns, and Follow-Ups",
        "Recent Raw Context Boundary",
    ]
    title_line = "# Model-Assisted Semantic Compression Summary"
    coverage_heading = "### Mandatory Evidence Coverage"
    allowed_heading_lines = {title_line, coverage_heading, *(f"## {heading}" for heading in required_headings)}
    body_lines = visible_body.splitlines()
    heading_entries = [
        (line_no, raw_line.strip())
        for line_no, raw_line in enumerate(body_lines, start=1)
        if raw_line.strip().startswith("#")
    ]
    unexpected_headings = [entry for entry in heading_entries if entry[1] not in allowed_heading_lines]
    if unexpected_headings:
        errors.append(f"model summary contains unsupported Markdown headings: {unexpected_headings[:12]}")
    if sum(1 for _line_no, line in heading_entries if line == title_line) != 1:
        errors.append("model summary must contain exactly one required title heading")
    actual_required_heading_lines = [
        line for _line_no, line in heading_entries if line.startswith("## ") and line != coverage_heading
    ]
    expected_required_heading_lines = [f"## {heading}" for heading in required_headings]
    if actual_required_heading_lines != expected_required_heading_lines:
        errors.append("model summary semantic section headings are missing, duplicated, renamed, or out of order")
    coverage_positions = [line_no for line_no, line in heading_entries if line == coverage_heading]
    if len(coverage_positions) != 1:
        errors.append("model summary must contain exactly one ### Mandatory Evidence Coverage subsection")

    coverage_entries: Dict[str, str] = {}
    coverage_duplicates: List[int] = []
    coverage_line_errors: List[Tuple[int, str]] = []
    coverage_body_line_numbers: set = set()
    if coverage_positions:
        coverage_start = coverage_positions[0]
        evidence_heading_line = next(
            (line_no for line_no, line in heading_entries if line == "## Evidence and Source Anchors"),
            None,
        )
        next_level_two = next(
            (
                line_no
                for line_no, line in heading_entries
                if line_no > coverage_start and line.startswith("## ")
            ),
            len(body_lines) + 1,
        )
        if evidence_heading_line is None or not (evidence_heading_line < coverage_start < next_level_two):
            errors.append("Mandatory Evidence Coverage must be inside the Evidence and Source Anchors section")
        decoder = json.JSONDecoder()
        for line_no in range(coverage_start + 1, next_level_two):
            raw_line = body_lines[line_no - 1]
            line = raw_line.strip()
            if not line:
                continue
            coverage_body_line_numbers.add(line_no)
            prefix_match = re.match(r"^- L(\d{1,9}) support_text_json=", line)
            if prefix_match is None:
                coverage_line_errors.append((line_no, truncate(line, 180)))
                continue
            anchor = int(prefix_match.group(1))
            remainder = line[prefix_match.end():]
            try:
                excerpt, end = decoder.raw_decode(remainder)
            except json.JSONDecodeError:
                coverage_line_errors.append((line_no, "support_text_json is not one valid JSON string"))
                continue
            if not isinstance(excerpt, str) or remainder[end:] != " disposition=covered":
                coverage_line_errors.append((line_no, "coverage line has trailing text or a non-string support value"))
                continue
            key = str(anchor)
            if key in coverage_entries:
                coverage_duplicates.append(anchor)
                continue
            coverage_entries[key] = excerpt
    if coverage_line_errors:
        errors.append(f"model summary has malformed mandatory coverage lines: {coverage_line_errors[:12]}")
    if coverage_duplicates:
        errors.append(f"model summary repeats mandatory coverage anchors: {sorted(set(coverage_duplicates))[:20]}")
    expected_claim_keys = set(normalized_claim_sources)
    actual_claim_keys = set(coverage_entries)
    missing_claim_coverage = sorted(expected_claim_keys - actual_claim_keys, key=int)
    unknown_claim_coverage = sorted(actual_claim_keys - expected_claim_keys, key=int)
    if missing_claim_coverage:
        errors.append(f"model summary lacks mandatory claim support for anchors: {missing_claim_coverage[:20]}")
    if unknown_claim_coverage:
        errors.append(f"model summary has mandatory claim support for unknown anchors: {unknown_claim_coverage[:20]}")
    invalid_claim_excerpts: List[JsonObj] = []
    for key in sorted(expected_claim_keys.intersection(actual_claim_keys), key=int):
        source = normalized_claim_sources[key]
        excerpt = coverage_entries[key]
        minimum_chars = min(12, len(source.strip()))
        if (
            not excerpt.strip()
            or len(excerpt.strip()) < minimum_chars
            or excerpt not in source
        ):
            invalid_claim_excerpts.append(
                {
                    "line": int(key),
                    "reason": "support excerpt must be a meaningful exact substring of its source record",
                    "minimumChars": minimum_chars,
                }
            )
    if invalid_claim_excerpts:
        errors.append(f"model summary mandatory claim support is invalid: {invalid_claim_excerpts[:20]}")

    anchor_scan_lines = list(body_lines)
    for line_no in coverage_body_line_numbers:
        line = body_lines[line_no - 1].strip()
        match = re.match(r"^- L(\d{1,9}) support_text_json=", line)
        anchor_scan_lines[line_no - 1] = f"- L{match.group(1)} disposition=covered" if match else line
    anchor_scan_body = "\n".join(anchor_scan_lines)
    if "<!--" in anchor_scan_body or "-->" in anchor_scan_body:
        errors.append("model summary body contains an extra or unclosed HTML comment marker")
    omitted_lines = {idx + 1 for idx in omitted_indexes}
    allowed_lines = set(int(line) for line in allowed_anchor_lines) if allowed_anchor_lines is not None else None
    anchors = model_summary_anchor_lines(anchor_scan_body)
    handoff_anchors = model_summary_handoff_anchor_lines(anchor_scan_body)
    unique_anchors = sorted(set(anchors))
    invalid_range = [line for line in unique_anchors if line < 1 or line > total_records]
    if invalid_range:
        errors.append(f"model summary cites line anchors outside the JSONL range: {invalid_range[:20]}")
    outside_omitted = [line for line in unique_anchors if line not in omitted_lines]
    if outside_omitted:
        errors.append(f"model summary cites lines that are not in the summarized omitted set: {outside_omitted[:20]}")
    if allowed_lines is not None:
        outside_pack = [line for line in unique_anchors if line not in allowed_lines]
        if outside_pack:
            errors.append(f"model summary cites lines that were not included in the generated evidence pack: {outside_pack[:20]}")
    anchor_population = allowed_lines if allowed_lines is not None and allowed_lines else omitted_lines
    min_anchor_count = min(8, max(1, len(anchor_population) // 80))
    if len(unique_anchors) < min_anchor_count:
        errors.append(
            f"model summary needs at least {min_anchor_count} distinct omitted-line anchors; found {len(unique_anchors)}"
        )
    normalized_groups = {
        str(name): sorted(set(int(line) for line in lines))
        for name, lines in (required_anchor_groups or {}).items()
        if lines
    }
    missing_anchor_groups = [
        name for name, lines in normalized_groups.items() if not set(lines).intersection(unique_anchors)
    ]
    if missing_anchor_groups:
        errors.append(
            "model summary does not cite every required evidence coverage group: "
            f"{missing_anchor_groups[:20]}"
        )
    invalid_handoff_anchors = sorted(
        set(anchor for anchor in handoff_anchors if anchor < 1 or anchor > allowed_handoff_anchor_count)
    )
    if invalid_handoff_anchors:
        errors.append(f"model summary cites handoff anchors not shown in the evidence pack: {invalid_handoff_anchors[:20]}")
    normalized_handoff_groups = required_handoff_anchor_groups(allowed_handoff_anchor_count)
    unique_handoff_anchors = set(handoff_anchors)
    missing_handoff_groups = [
        name for name, lines in normalized_handoff_groups.items()
        if not set(lines).intersection(unique_handoff_anchors)
    ]
    if missing_handoff_groups:
        errors.append(
            "model summary does not cite every required handoff coverage group: "
            f"{missing_handoff_groups[:20]}"
        )
    lower = anchor_scan_body.lower()
    suspicious_patterns = [
        r"\bas an ai(?: language)? model\b",
        r"\b(?:i|we)\s+(?:do not|don't|lack)\s+(?:currently\s+)?(?:have\s+)?access\b",
        r"\b(?:file|data|information|context|source|content)\s+(?:was|were|is|are)\s+not\s+(?:provided|available|accessible)\b",
        r"\bno\s+(?:source|evidence|information|context)\s+(?:was\s+)?provided\b",
        r"\baccess\s+to\s+(?:the\s+)?(?:file|data|source|context)\s+is\s+unavailable\b",
    ]
    found_suspicious = [pattern for pattern in suspicious_patterns if re.search(pattern, lower)]
    if found_suspicious:
        errors.append(f"model summary contains refusal/no-access boilerplate: {found_suspicious[:5]}")
    unanchored_lines: List[Tuple[int, str]] = []
    for line_no, raw_line in enumerate(anchor_scan_lines, start=1):
        line = raw_line.strip()
        if not line:
            continue
        if line in allowed_heading_lines:
            continue
        if line == "Unknown from provided anchors.":
            continue
        if not model_summary_anchor_lines(line) and not model_summary_handoff_anchor_lines(line):
            unanchored_lines.append((line_no, truncate(line, 160)))
    if unanchored_lines:
        errors.append(f"model summary has substantive lines without line anchors: {unanchored_lines[:8]}")
    missing_headings = [heading for heading in required_headings if f"## {heading}" not in actual_required_heading_lines]
    if missing_headings:
        errors.append(f"model summary is missing required semantic sections: {missing_headings}")
    section_anchor_errors: List[str] = []
    heading_matches = list(re.finditer(r"^## (.+?)$", anchor_scan_body, re.MULTILINE))
    for heading in required_headings:
        match_index = next(
            (
                pos for pos, match in enumerate(heading_matches)
                if match.group(1).strip().casefold() == heading.casefold()
            ),
            None,
        )
        if match_index is None:
            continue
        start = heading_matches[match_index].end()
        end = heading_matches[match_index + 1].start() if match_index + 1 < len(heading_matches) else len(anchor_scan_body)
        section_text = anchor_scan_body[start:end]
        if not model_summary_anchor_lines(section_text) and not model_summary_handoff_anchor_lines(section_text):
            section_anchor_errors.append(heading)
    if section_anchor_errors:
        errors.append(f"required semantic sections lack evidence anchors: {section_anchor_errors}")
    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "chars": len(stripped),
        "metadata": metadata,
        "anchor_count": len(anchors),
        "distinct_anchor_count": len(unique_anchors),
        "anchor_samples": unique_anchors[:30],
        "allowed_anchor_count": len(allowed_lines) if allowed_lines is not None else None,
        "evidence_anchor_lines_digest": expected_evidence_anchor_lines_digest,
        "required_anchor_groups_digest": expected_required_anchor_groups_digest,
        "required_anchor_group_count": len(normalized_groups),
        "missing_required_anchor_groups": missing_anchor_groups,
        "handoff_summary_digest": expected_handoff_value,
        "handoff_anchor_count": len(handoff_anchors),
        "allowed_handoff_anchor_count": allowed_handoff_anchor_count,
        "required_handoff_anchor_groups": normalized_handoff_groups,
        "missing_required_handoff_anchor_groups": missing_handoff_groups,
        "unanchored_line_count": len(unanchored_lines),
        "unanchored_line_samples": unanchored_lines[:8],
        "required_min_anchor_count": min_anchor_count,
        "required_section_anchor_errors": section_anchor_errors,
        "pack_request_digest": expected_pack_request_digest,
        "required_claim_sources_digest": expected_claim_digest,
        "required_claim_source_count": len(normalized_claim_sources),
        "mandatory_claim_coverage_count": len(coverage_entries),
        "missing_mandatory_claim_coverage": missing_claim_coverage,
        "unknown_mandatory_claim_coverage": unknown_claim_coverage,
        "invalid_mandatory_claim_support": invalid_claim_excerpts[:20],
    }


def compose_model_assisted_summary(
    model_summary_text: str,
    deterministic_summary_text: str,
    summary_char_budget: int,
) -> str:
    model_text = model_summary_text.strip()
    fixed_parts = [
        "# Codex Offline Compression Summary",
        "This candidate uses model-assisted semantic compression. The model-authored section below was accepted only after source-digest, summary-source, evidence-group, and line-anchor validation. The deterministic safety appendix remains a bounded structural backstop.",
        "## Model-Assisted Semantic Summary",
        model_text,
        "## Deterministic Safety Appendix",
    ]
    fixed_text = "\n\n".join(fixed_parts)
    available_safety_chars = summary_char_budget - len(fixed_text) - 2
    minimum_safety_chars = min(800, len(deterministic_summary_text.strip()))
    if available_safety_chars < minimum_safety_chars:
        raise ValueError(
            f"summary character budget {summary_char_budget} cannot contain the accepted model summary "
            f"({len(model_text)} chars) plus the minimum deterministic appendix; increase --summary-char-budget"
        )
    safety_appendix = truncate(
        deterministic_summary_text.strip(),
        min(18000, available_safety_chars),
    )
    rendered = fixed_text + "\n\n" + safety_appendix
    if len(rendered) > summary_char_budget:
        raise AssertionError("model summary composition exceeded the checked summary character budget")
    if model_text not in rendered:
        raise AssertionError("accepted model summary changed during composition")
    return rendered


def compact_summary_message_content(obj: JsonObj) -> str:
    msg = obj.get("message")
    if isinstance(msg, dict):
        content = msg.get("content")
        if isinstance(content, str):
            return content
    return message_text(obj)


def collect_prior_compact_summaries(
    omitted: Sequence[JsonObj],
    omitted_indexes: Sequence[int],
) -> List[Dict[str, Any]]:
    summaries: List[Dict[str, Any]] = []
    for obj, idx in zip(omitted, omitted_indexes):
        if obj.get("isCompactSummary") is not True:
            continue
        text = compact_summary_message_content(obj)
        if not text.strip():
            continue
        summaries.append(
            {
                "sourceLine": idx + 1,
                "uuid": obj.get("uuid"),
                "chars": len(text),
                "sha256Prefix": stable_digest(text),
                "text": text,
            }
        )
    return summaries


def format_verbatim_prior_summary_block(prior_summaries: Sequence[Dict[str, Any]]) -> str:
    lines = [
        "# Preserved Prior Compact Summaries",
        "",
        "The following prior `isCompactSummary` message contents are copied verbatim because the user explicitly requested preservation across repeated compression. They are embedded inside this new single compact summary; the old compact records are not kept as additional live compact pairs.",
    ]
    for pos, item in enumerate(prior_summaries, 1):
        lines.extend(
            [
                "",
                f"## Prior Compact Summary {pos}",
                f"<!-- source_line: {item.get('sourceLine')} uuid: {item.get('uuid') or 'none'} sha256_prefix: {item.get('sha256Prefix')} chars: {item.get('chars')} -->",
                "",
                str(item.get("text") or ""),
            ]
        )
    return "\n".join(lines).strip()


def apply_prior_summary_verbatim_policy(
    summary_text: str,
    omitted: Sequence[JsonObj],
    omitted_indexes: Sequence[int],
    summary_char_budget: int,
    requested: bool,
) -> Tuple[str, Dict[str, Any]]:
    prior_summaries = collect_prior_compact_summaries(omitted, omitted_indexes)
    info: Dict[str, Any] = {
        "requested": bool(requested),
        "mode": "not-requested",
        "budgetFactor": PRIOR_SUMMARY_VERBATIM_BUDGET_FACTOR,
        "baseSummaryChars": len(summary_text),
        "maxAllowedSummaryChars": summary_char_budget,
        "priorSummaryCount": len(prior_summaries),
        "priorSummaryChars": sum(int(item.get("chars") or 0) for item in prior_summaries),
        "priorSummaryDigests": [
            {
                "sourceLine": item.get("sourceLine"),
                "uuid": item.get("uuid"),
                "chars": item.get("chars"),
                "sha256Prefix": item.get("sha256Prefix"),
            }
            for item in prior_summaries
        ],
        "preservedCount": 0,
        "fallbackReason": None,
    }
    if not requested:
        return summary_text, info
    expanded_budget = max(summary_char_budget, int(summary_char_budget * PRIOR_SUMMARY_VERBATIM_BUDGET_FACTOR))
    info["maxAllowedSummaryChars"] = expanded_budget
    if not prior_summaries:
        info["mode"] = "requested-no-prior-summaries"
        return summary_text, info

    verbatim_block = format_verbatim_prior_summary_block(prior_summaries)
    candidate = "\n\n".join(
        [
            verbatim_block,
            "# Current Compression Layer",
            summary_text.strip(),
        ]
    ).strip() + "\n"
    info["candidateSummaryChars"] = len(candidate)
    if len(candidate) <= expanded_budget:
        info["mode"] = "verbatim-preserved"
        info["preservedCount"] = len(prior_summaries)
        return candidate, info

    info["mode"] = "fallback-folded"
    info["fallbackReason"] = (
        f"verbatim prior summaries would make summary {len(candidate)} chars, "
        f"exceeding expanded budget {expanded_budget} chars "
        f"({PRIOR_SUMMARY_VERBATIM_BUDGET_FACTOR:.1f}x summary_char_budget); "
        "used the normal folded-summary path instead"
    )
    return summary_text, info


def pack_json_string(text: str) -> str:
    return (
        json.dumps(text, ensure_ascii=False)
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
        .replace("\u0085", "\\u0085")
    )


def model_evidence_record(obj: JsonObj, original_line: int) -> Optional[Dict[str, Any]]:
    is_prior_summary = obj.get("isCompactSummary") is True
    semantic_txt = semantic_message_text(obj)
    is_human_semantic = is_human_user_record(obj) and bool(semantic_txt.strip())
    is_assistant_semantic = (
        obj.get("type") == "assistant"
        and bool(semantic_txt.strip())
    )
    mandatory_semantic = is_human_semantic or is_assistant_semantic
    txt = semantic_txt if mandatory_semantic or is_prior_summary else record_text(obj)
    noisy = is_noisy_text(txt)
    if not txt or (noisy and not mandatory_semantic and not is_prior_summary):
        return None
    role = api_role(obj) or str(obj.get("type", "<missing>"))
    timestamp = obj.get("timestamp") or ""
    uid = obj.get("uuid") or ""
    prefix = f"L{original_line} type={obj.get('type')} role={role}"
    if timestamp:
        prefix += f" ts={timestamp}"
    if uid:
        prefix += f" uuid={uid}"
    importance = 0
    if is_human_semantic:
        importance += 5
    if text_has_any(txt, IMPORTANT_WORDS):
        importance += 4
    if is_prior_summary:
        importance += 4
    if obj.get("type") == "system" and (obj.get("subtype") == "api_error" or obj.get("error")):
        importance += 3
    if obj.get("type") == "assistant":
        importance += 1
        decision_score = assistant_research_decision_score(txt)
        if decision_score:
            importance += min(24, 4 + decision_score)
    if extract_paths(txt):
        importance += 1
    classes: List[str] = []
    if is_human_semantic:
        classes.append("human-user")
        if text_has_any(txt, IMPORTANT_WORDS):
            classes.append("human-constraint")
    if is_assistant_semantic:
        classes.append("assistant-semantic")
        if assistant_research_decision_score(txt):
            classes.append("assistant-research")
            classes.extend(
                f"assistant-research-{group}"
                for group in assistant_decision_language_groups(txt)
            )
    if tool_use_ids(obj) or is_tool_result_user_record(obj) or extract_paths(txt):
        classes.append("source-tool")
    if is_prior_summary:
        classes.append("prior-summary")
    if noisy:
        classes.append("source-text-warning")
    if obj.get("type") == "system" and (obj.get("subtype") == "api_error" or obj.get("error")):
        classes.append("system-error")
    if is_prior_summary or mandatory_semantic:
        class_label = ",".join(classes) if classes else "general"
        line = f"- {prefix} evidence_class={class_label} full_text_json={pack_json_string(txt)}"
    else:
        class_label = ",".join(classes) if classes else "general"
        line = f"- {prefix} evidence_class={class_label}\n  {one_line(txt.strip(), 900)}"
    return {
        "idx": original_line - 1,
        "lineNumber": original_line,
        "importance": importance,
        "line": line,
        "classes": classes,
        "priorSummary": is_prior_summary,
        "mandatorySemantic": mandatory_semantic,
        "semanticKind": "human-user" if is_human_semantic else "assistant-semantic" if is_assistant_semantic else None,
        "claimSource": txt if is_prior_summary or mandatory_semantic else None,
        "sourceTextWarning": noisy,
    }


def model_evidence_priority(records: Sequence[JsonObj], idx: int, base_importance: int) -> int:
    obj = records[idx]
    txt = record_text(obj)
    priority = base_importance
    if is_human_user_record(obj):
        priority += 50
        if text_has_any(txt, IMPORTANT_WORDS):
            priority += 160
    if obj.get("type") == "assistant":
        decision_score = assistant_research_decision_score(txt)
        if decision_score:
            priority += 35 + min(decision_score, 35)
    if obj.get("isCompactSummary"):
        priority += 34
    if obj.get("type") == "system" and (obj.get("subtype") == "api_error" or obj.get("error")):
        priority += 28
    if is_tool_result_user_record(obj):
        if text_has_any(txt, IMPORTANT_WORDS):
            priority += 18
        if extract_paths(txt):
            priority += 12
    if extract_paths(txt):
        priority += 8
    return priority


def select_model_evidence_payload(
    records: Sequence[JsonObj],
    omitted_indexes: Sequence[int],
    char_budget: int,
    estimated_token_budget: Optional[int] = None,
) -> Dict[str, Any]:
    omitted_order = {idx: pos for pos, idx in enumerate(omitted_indexes)}
    omitted_count = len(omitted_indexes)

    def temporal_group(idx: int) -> str:
        pos = omitted_order[idx]
        bucket = min(2, (pos * 3) // max(1, omitted_count))
        return ("temporal-early", "temporal-middle", "temporal-late")[bucket]

    evidence: List[Dict[str, Any]] = []
    optional_omissions: Dict[int, str] = {}
    for idx in omitted_indexes:
        item = model_evidence_record(records[idx], idx + 1)
        if item is None:
            if record_text(records[idx]).strip():
                optional_omissions[idx] = "noise-or-ineligible"
            continue
        if int(item["importance"]) <= 0:
            optional_omissions[idx] = "zero-priority"
            continue
        item["priority"] = model_evidence_priority(records, idx, int(item["importance"]))
        item["temporalGroup"] = temporal_group(idx)
        evidence.append(item)
    if not evidence:
        return {
            "lines": [], "anchorLines": [], "truncated": bool(optional_omissions),
            "requiredAnchorGroups": {}, "selectedRecordCount": 0,
            "mandatorySemanticRecordCount": 0, "estimatedTokens": 0,
            "requiredClaimSources": {},
            "requiredClaimSourcesDigest": canonical_json_sha256({}),
            "optionalEvidenceOmittedCount": len(optional_omissions),
            "optionalEvidenceOmittedLinesDigest": anchor_lines_digest(
                [idx + 1 for idx in optional_omissions]
            ),
            "optionalEvidenceOmissionReasons": dict(collections.Counter(optional_omissions.values())),
        }

    prior_items = [item for item in evidence if item["priorSummary"]]
    prior_chars = sum(len(str(item["line"])) + 1 for item in prior_items)
    if prior_chars > char_budget:
        raise ValueError(
            f"prior compact summary evidence requires {prior_chars} chars but the model evidence budget is "
            f"{char_budget}; increase --model-pack-char-budget so prior summaries are never clipped"
        )

    required_items: Dict[str, Dict[str, Any]] = {}

    def highest(items: Sequence[Dict[str, Any]], prefer_latest: bool = True) -> Optional[Dict[str, Any]]:
        if not items:
            return None
        return max(
            items,
            key=lambda item: (
                int(item["priority"]),
                int(item["idx"]) if prefer_latest else -int(item["idx"]),
            ),
        )

    for group in ("temporal-early", "temporal-middle", "temporal-late"):
        candidate = highest([item for item in evidence if item["temporalGroup"] == group])
        if candidate is not None:
            required_items[group] = candidate
    for group in ("human-user", "assistant-research", "source-tool"):
        candidate = highest([item for item in evidence if group in item["classes"]])
        if candidate is not None:
            required_items[group] = candidate
    for item in evidence:
        if not item.get("mandatorySemantic"):
            continue
        semantic_kind = str(item.get("semanticKind") or "semantic")
        required_items[f"semantic-{semantic_kind}-L{int(item['lineNumber']):09d}"] = item
    required_items["latest-evidence"] = evidence[-1]
    for item in prior_items:
        required_items[f"prior-summary-L{item['lineNumber']}"] = item

    selected: Dict[int, Dict[str, Any]] = {}
    used = 0
    used_tokens = 0
    truncated = bool(optional_omissions)

    def add_item(item: Dict[str, Any], required_reason: Optional[str] = None) -> None:
        nonlocal used, used_tokens, truncated
        idx = int(item["idx"])
        if idx in selected:
            return
        line_len = len(str(item["line"])) + 1
        line_tokens = estimate_tokens(str(item["line"])) + 1
        exceeds_chars = used + line_len > char_budget
        exceeds_tokens = (
            estimated_token_budget is not None
            and used_tokens + line_tokens > estimated_token_budget
        )
        if exceeds_chars or exceeds_tokens:
            if required_reason:
                if item["priorSummary"]:
                    if exceeds_tokens:
                        raise ValueError(
                            f"prior compact summary evidence at L{item['lineNumber']} does not fit the model evidence "
                            "token budget; increase --model-pack-estimated-token-budget only if the summarizing "
                            "model can read the resulting pack"
                        )
                    raise ValueError(
                        f"prior compact summary evidence at L{item['lineNumber']} does not fit the model evidence budget; "
                        "increase --model-pack-char-budget"
                    )
                if exceeds_tokens:
                    raise ValueError(
                        f"model evidence token budget {estimated_token_budget} cannot satisfy required coverage group "
                        f"{required_reason}; increase --model-pack-estimated-token-budget only if the summarizing "
                        "model can read the resulting pack"
                    )
                raise ValueError(
                    f"model evidence budget {char_budget} cannot satisfy required coverage group {required_reason}; "
                    "increase --model-pack-char-budget"
                )
            truncated = True
            return
        selected[idx] = item
        used += line_len
        used_tokens += line_tokens

    for item in prior_items:
        add_item(item, required_reason=f"prior-summary-L{item['lineNumber']}")
    for name, item in required_items.items():
        add_item(item, required_reason=name)

    for item in sorted(evidence, key=lambda value: (-int(value["priority"]), -int(value["idx"]))):
        add_item(item)

    ordered = [selected[idx] for idx in sorted(selected)]
    for item in evidence:
        idx = int(item["idx"])
        if idx not in selected and not item.get("mandatorySemantic") and not item.get("priorSummary"):
            optional_omissions.setdefault(idx, "pack-budget")
    required_groups = {
        name: [int(item["lineNumber"])]
        for name, item in required_items.items()
    }
    required_claim_sources = {
        str(int(item["lineNumber"])): str(item.get("claimSource") or "")
        for item in ordered
        if item.get("mandatorySemantic") or item.get("priorSummary")
    }
    truncated = truncated or len(selected) < len(evidence) or bool(optional_omissions)
    return {
        "lines": [str(item["line"]) for item in ordered],
        "anchorLines": [int(item["lineNumber"]) for item in ordered],
        "truncated": truncated,
        "requiredAnchorGroups": required_groups,
        "selectedRecordCount": len(ordered),
        "mandatorySemanticRecordCount": sum(1 for item in ordered if item.get("mandatorySemantic")),
        "estimatedTokens": used_tokens,
        "requiredClaimSources": required_claim_sources,
        "requiredClaimSourcesDigest": canonical_json_sha256(required_claim_sources),
        "optionalEvidenceOmittedCount": len(optional_omissions),
        "optionalEvidenceOmittedLinesDigest": anchor_lines_digest(
            [idx + 1 for idx in optional_omissions]
        ),
        "optionalEvidenceOmissionReasons": dict(collections.Counter(optional_omissions.values())),
    }


def select_model_evidence(records: Sequence[JsonObj], omitted_indexes: Sequence[int], char_budget: int) -> Tuple[List[str], List[int], bool]:
    payload = select_model_evidence_payload(records, omitted_indexes, char_budget)
    return list(payload["lines"]), list(payload["anchorLines"]), bool(payload["truncated"])


def select_model_evidence_for_pack(records: Sequence[JsonObj], omitted_indexes: Sequence[int], model_pack_char_budget: int) -> Tuple[List[str], List[int], bool]:
    evidence_budget = max(8000, model_pack_char_budget - 9000)
    return select_model_evidence(records, omitted_indexes, evidence_budget)


def render_model_summary_pack_text(
    input_path: pathlib.Path,
    records: Sequence[JsonObj],
    omitted_indexes: Sequence[int],
    kept_count: int,
    source_digest: str,
    omitted_digest: str,
    preserve_mode: str,
    selected_leaf_uuid: Optional[str],
    char_budget: int,
    evidence_lines: Sequence[str],
    evidence_anchor_lines: Sequence[int],
    required_anchor_groups: Dict[str, Sequence[int]],
    truncated: bool,
    pack_request_digest: str,
    required_claim_sources_digest: str,
    required_claim_anchor_lines: Sequence[int],
    optional_evidence_omitted_count: int = 0,
    optional_evidence_omitted_lines_digest: Optional[str] = None,
    optional_evidence_omission_reasons: Optional[Dict[str, int]] = None,
    handoff_summary_text: Optional[str] = None,
    handoff_summary_digest: Optional[str] = None,
    preserve_prior_summaries_verbatim: bool = False,
    prior_summary_count: int = 0,
    prior_summary_chars: int = 0,
    session_lineage_compatibility: bool = False,
    session_lineage_transition_count: int = 0,
    mandatory_semantic_record_count: int = 0,
    estimated_token_budget: int = DEFAULT_MODEL_PACK_ESTIMATED_TOKEN_BUDGET,
) -> str:
    evidence_lines_digest = anchor_lines_digest(evidence_anchor_lines)
    required_groups_digest = anchor_groups_digest(required_anchor_groups)
    omitted_line_numbers = [idx + 1 for idx in omitted_indexes]
    line_range = f"{min(omitted_line_numbers)}-{max(omitted_line_numbers)}" if omitted_line_numbers else "none"
    pack_body = "\n".join(evidence_lines) if evidence_lines else "No textual evidence extracted; deterministic fallback may be safer."
    prior_summary_note = (
        "User requested verbatim preservation of prior compact summaries. The script will try to embed old isCompactSummary message.content verbatim in the new single compact summary, allowing up to 1.5x summary_char_budget for that summary text. Do not spend model-summary space rephrasing those prior summaries unless needed for current-state integration."
        if preserve_prior_summaries_verbatim
        else "Normal repeated-compression mode: old compact summaries are evidence to fold into the new model summary."
    )
    handoff_lines = physical_text_lines(handoff_summary_text or "")
    handoff_body = "\n".join(
        f"- H{idx} full_text_json={pack_json_string(line)}"
        for idx, line in enumerate(handoff_lines, start=1)
    )
    if not handoff_body:
        handoff_body = "No external handoff summary supplied."
    handoff_groups = required_handoff_anchor_groups(len(handoff_lines))
    required_handoff_group_lines = "\n".join(
        f"- `{name}`: " + ", ".join(f"H{line}" for line in lines)
        for name, lines in handoff_groups.items()
    ) or "- No H-anchor coverage is required because no external handoff was supplied."
    required_group_lines = "\n".join(
        f"- `{name}`: " + ", ".join(f"L{line}" for line in lines)
        for name, lines in sorted(required_anchor_groups.items())
    ) or "- No required L-anchor groups were generated."
    required_claim_lines = "\n".join(
        f"- L{line}" for line in sorted(set(int(value) for value in required_claim_anchor_lines))
    ) or "- No mandatory claim-support entries are required."
    optional_reason_text = json.dumps(optional_evidence_omission_reasons or {}, ensure_ascii=False, sort_keys=True)
    return f"""# v11 Model-Assisted Summary Pack

This pack is evidence for writing a semantic summary. It is not a JSONL file. Do not edit UUIDs, parentUuid, last-prompt, compact records, or tool_use/tool_result structure.

## Required Output Metadata

Copy this exact comment to the top of the final model summary:

<!-- {MODEL_SUMMARY_MARKER}
source_sha256: {source_digest}
summary_source_sha256: {omitted_digest}
evidence_anchor_lines_digest: {evidence_lines_digest}
required_anchor_groups_digest: {required_groups_digest}
handoff_summary_digest: {handoff_summary_digest or 'none'}
pack_request_digest: {pack_request_digest}
required_claim_sources_digest: {required_claim_sources_digest}
-->

## Compression Context

- Source file label: SOURCE_JSONL
- Source SHA-256: {source_digest}
- Summary-source SHA-256: {omitted_digest}
- Total JSONL records: {len(records)}
- Summary-source physical span: {line_range}
- Active-chain records selected for summary: {len(omitted_indexes)}
- Recent raw records preserved outside this summary: {kept_count}
- Preserve mode: {preserve_mode}
- One-way session-lineage compatibility: {session_lineage_compatibility}
- Session-lineage transitions summarized before recent raw context: {session_lineage_transition_count}
- Selected leaf UUID: {selected_leaf_uuid}
- Evidence truncated by pack budget: {truncated}
- Configured zero-dependency pack token ceiling: {estimated_token_budget}
- Evidence anchor lines shown: {len(evidence_anchor_lines)}
- Mandatory full-text semantic records shown: {mandatory_semantic_record_count}
- Evidence anchor lines digest: {evidence_lines_digest}
- Required anchor groups digest: {required_groups_digest}
- Pack request digest: {pack_request_digest}
- Required claim sources digest: {required_claim_sources_digest}
- External handoff summary digest: {handoff_summary_digest or 'none'}
- Optional evidence omitted: {optional_evidence_omitted_count}
- Optional evidence omitted line-set digest: {optional_evidence_omitted_lines_digest or anchor_lines_digest([])}
- Optional evidence omission reasons: {optional_reason_text}
- Preserve prior compact summaries verbatim requested: {preserve_prior_summaries_verbatim}
- Prior compact summaries in omitted set: {prior_summary_count}
- Prior compact summary characters in omitted set: {prior_summary_chars}
- Prior compact summary handling note: {prior_summary_note}

## Required Model Behavior

- Use only facts supported by line anchors in this pack.
- Cite claims with `L<number>` anchors, for example `L42`.
- Cite only `L<number>` anchors that appear under `Evidence Records` in this pack. Do not cite omitted JSONL lines that were not shown here.
- If an external handoff section is present, cite its displayed `H<number>` anchor on every claim that depends on it. Never cite an H anchor that is not shown.
- Preserve chronology. If early and later facts conflict, mark the later fact as current and the earlier fact as superseded.
- Preserve user wording, final decisions, rejected alternatives, reasons, evidence provenance, risks, unresolved questions, and style/tone constraints.
- Preserve assistant/model research decisions and rationales as first-class memory: what the assistant concluded, why, what evidence it checked, which alternatives it rejected, and which prior plan it superseded. This applies in any language used in the transcript.
- For legal, humanities, art, brand/design strategy, document research, feasibility analysis, and software projects, do not collapse historical nuance into generic bullets.
- Every summarized human message and every summarized assistant `text`/`thinking` message appears as complete `full_text_json` evidence and has its own required L-anchor group. A source-text warning does not make mandatory evidence optional.
- Tool calls, file/tool results, errors, and other source evidence are supplementary records selected after the mandatory semantic ledger. Use them to preserve provenance and checked evidence without copying large raw payloads blindly.
- If evidence is insufficient, write the exact standalone line `Unknown from provided anchors.` instead of guessing. No bullet prefix, case change, or missing period is accepted.
- Cite at least one displayed anchor from every group under `Required Anchor Coverage`. The groups force early/middle/late chronology, recent omitted evidence, every semantic message, source/tool evidence, and every prior compact summary when those classes exist.
- When a handoff is present, also cite every group under `Required Handoff Anchor Coverage`; this requires temporal coverage without copying the handoff verbatim into the final summary.
- Under `## Evidence and Source Anchors`, add the exact `### Mandatory Evidence Coverage` subsection. For every anchor under `Required Claim Support`, write exactly one line in this form: `- L42 support_text_json="exact source substring" disposition=covered`. The JSON string must decode to a meaningful exact substring of that L record.

## Required Final Summary Shape

# Model-Assisted Semantic Compression Summary

## Current State
## Timeline and Supersessions
## Decisions and Reasons
## Assistant Research Decisions and Rationales
## Rejected or Superseded Alternatives
## Evidence and Source Anchors
## User Wording and Constraints
## Risks, Unknowns, and Follow-Ups
## Recent Raw Context Boundary

## Required Anchor Coverage

{required_group_lines}

## Required Handoff Anchor Coverage

{required_handoff_group_lines}

## Required Claim Support

{required_claim_lines}

## Evidence Records

{pack_body}

## External Handoff Summary

{handoff_body}
"""


def build_model_summary_pack_payload(
    input_path: pathlib.Path,
    records: Sequence[JsonObj],
    omitted_indexes: Sequence[int],
    kept_count: int,
    source_digest: str,
    omitted_digest: str,
    preserve_mode: str,
    selected_leaf_uuid: Optional[str],
    char_budget: int,
    pack_request_digest: str,
    handoff_summary_text: Optional[str] = None,
    handoff_summary_digest: Optional[str] = None,
    preserve_prior_summaries_verbatim: bool = False,
    session_lineage_compatibility: bool = False,
    session_lineage_transition_count: int = 0,
    estimated_token_budget: int = DEFAULT_MODEL_PACK_ESTIMATED_TOKEN_BUDGET,
) -> Dict[str, Any]:
    if estimated_token_budget < 10000:
        raise ValueError("--model-pack-estimated-token-budget must be at least 10000")
    prior_summaries = collect_prior_compact_summaries(
        [records[idx] for idx in omitted_indexes],
        omitted_indexes,
    )
    prior_summary_chars = sum(int(item.get("chars") or 0) for item in prior_summaries)
    empty_claim_sources_digest = canonical_json_sha256({})
    empty_text = render_model_summary_pack_text(
        input_path=input_path,
        records=records,
        omitted_indexes=omitted_indexes,
        kept_count=kept_count,
        source_digest=source_digest,
        omitted_digest=omitted_digest,
        preserve_mode=preserve_mode,
        selected_leaf_uuid=selected_leaf_uuid,
        char_budget=char_budget,
        evidence_lines=[],
        evidence_anchor_lines=[],
        required_anchor_groups={},
        truncated=True,
        pack_request_digest=pack_request_digest,
        required_claim_sources_digest=empty_claim_sources_digest,
        required_claim_anchor_lines=[],
        handoff_summary_text=handoff_summary_text,
        handoff_summary_digest=handoff_summary_digest,
        preserve_prior_summaries_verbatim=preserve_prior_summaries_verbatim,
        prior_summary_count=len(prior_summaries),
        prior_summary_chars=prior_summary_chars,
        session_lineage_compatibility=session_lineage_compatibility,
        session_lineage_transition_count=session_lineage_transition_count,
        mandatory_semantic_record_count=0,
        estimated_token_budget=estimated_token_budget,
    )
    if len(empty_text) > char_budget:
        raise ValueError(
            f"model summary pack fixed evidence and complete handoff require {len(empty_text)} chars, "
            f"above --model-pack-char-budget {char_budget}; increase the pack budget"
        )
    empty_estimated_tokens = estimate_tokens(empty_text)
    if empty_estimated_tokens > estimated_token_budget:
        raise ValueError(
            f"model summary pack fixed evidence and complete handoff require approximately "
            f"{empty_estimated_tokens} tokens, above --model-pack-estimated-token-budget "
            f"{estimated_token_budget}; use a larger summarizing model or explicitly raise the token budget"
        )
    evidence_budget = max(0, char_budget - len(empty_text) - 200)
    evidence_token_budget = max(0, estimated_token_budget - empty_estimated_tokens)
    evidence_lines: List[str] = []
    evidence_anchor_lines: List[int] = []
    required_anchor_groups: Dict[str, Sequence[int]] = {}
    mandatory_semantic_record_count = 0
    required_claim_sources: Dict[str, str] = {}
    required_claim_sources_digest = empty_claim_sources_digest
    optional_evidence_omitted_count = 0
    optional_evidence_omitted_lines_digest = anchor_lines_digest([])
    optional_evidence_omission_reasons: Dict[str, int] = {}
    truncated = False
    pack_text = empty_text
    pack_estimated_tokens = empty_estimated_tokens
    for _ in range(8):
        evidence_payload = select_model_evidence_payload(
            records,
            omitted_indexes,
            evidence_budget,
            estimated_token_budget=evidence_token_budget,
        )
        evidence_lines = list(evidence_payload["lines"])
        evidence_anchor_lines = list(evidence_payload["anchorLines"])
        required_anchor_groups = dict(evidence_payload["requiredAnchorGroups"])
        mandatory_semantic_record_count = int(evidence_payload.get("mandatorySemanticRecordCount") or 0)
        required_claim_sources = dict(evidence_payload.get("requiredClaimSources") or {})
        required_claim_sources_digest = str(
            evidence_payload.get("requiredClaimSourcesDigest") or canonical_json_sha256(required_claim_sources)
        )
        optional_evidence_omitted_count = int(evidence_payload.get("optionalEvidenceOmittedCount") or 0)
        optional_evidence_omitted_lines_digest = str(
            evidence_payload.get("optionalEvidenceOmittedLinesDigest") or anchor_lines_digest([])
        )
        optional_evidence_omission_reasons = dict(
            evidence_payload.get("optionalEvidenceOmissionReasons") or {}
        )
        truncated = bool(evidence_payload["truncated"])
        pack_text = render_model_summary_pack_text(
            input_path=input_path,
            records=records,
            omitted_indexes=omitted_indexes,
            kept_count=kept_count,
            source_digest=source_digest,
            omitted_digest=omitted_digest,
            preserve_mode=preserve_mode,
            selected_leaf_uuid=selected_leaf_uuid,
            char_budget=char_budget,
            evidence_lines=evidence_lines,
            evidence_anchor_lines=evidence_anchor_lines,
            required_anchor_groups=required_anchor_groups,
            truncated=truncated,
            pack_request_digest=pack_request_digest,
            required_claim_sources_digest=required_claim_sources_digest,
            required_claim_anchor_lines=[int(line) for line in required_claim_sources],
            optional_evidence_omitted_count=optional_evidence_omitted_count,
            optional_evidence_omitted_lines_digest=optional_evidence_omitted_lines_digest,
            optional_evidence_omission_reasons=optional_evidence_omission_reasons,
            handoff_summary_text=handoff_summary_text,
            handoff_summary_digest=handoff_summary_digest,
            preserve_prior_summaries_verbatim=preserve_prior_summaries_verbatim,
            prior_summary_count=len(prior_summaries),
            prior_summary_chars=prior_summary_chars,
            session_lineage_compatibility=session_lineage_compatibility,
            session_lineage_transition_count=session_lineage_transition_count,
            mandatory_semantic_record_count=mandatory_semantic_record_count,
            estimated_token_budget=estimated_token_budget,
        )
        pack_estimated_tokens = estimate_tokens(pack_text)
        if len(pack_text) <= char_budget and pack_estimated_tokens <= estimated_token_budget:
            break
        if len(pack_text) > char_budget:
            overage = len(pack_text) - char_budget
            evidence_budget = max(0, evidence_budget - overage - 200)
        if pack_estimated_tokens > estimated_token_budget:
            token_overage = pack_estimated_tokens - estimated_token_budget
            evidence_token_budget = max(0, evidence_token_budget - token_overage - 500)
    if len(pack_text) > char_budget:
        raise ValueError(
            f"model summary pack overhead exceeds --model-pack-char-budget ({len(pack_text)} > {char_budget}); "
            "increase --model-pack-char-budget or reduce handoff summary size"
        )
    if pack_estimated_tokens > estimated_token_budget:
        raise ValueError(
            f"model summary pack is estimated at {pack_estimated_tokens} tokens, above "
            f"--model-pack-estimated-token-budget {estimated_token_budget}; optional evidence could not be reduced "
            "further without losing required semantic coverage"
        )
    visible_anchors = sorted(set(model_pack_evidence_anchor_lines(pack_text)))
    if set(visible_anchors) != set(evidence_anchor_lines):
        raise AssertionError("internal error: model pack anchor digest includes anchors not visible in pack text")
    required_group_anchors = {
        int(line) for lines in required_anchor_groups.values() for line in lines
    }
    if not required_group_anchors.issubset(set(visible_anchors)):
        raise AssertionError("internal error: required anchor group references evidence absent from the model pack")
    return {
        "text": pack_text,
        "evidence_anchor_lines": visible_anchors,
        "evidence_anchor_lines_digest": anchor_lines_digest(visible_anchors),
        "required_anchor_groups": required_anchor_groups,
        "required_anchor_groups_digest": anchor_groups_digest(required_anchor_groups),
        "pack_request_digest": pack_request_digest,
        "required_claim_sources": required_claim_sources,
        "required_claim_sources_digest": required_claim_sources_digest,
        "evidence_truncated": truncated,
        "optional_evidence_omitted_count": optional_evidence_omitted_count,
        "optional_evidence_omitted_lines_digest": optional_evidence_omitted_lines_digest,
        "optional_evidence_omission_reasons": optional_evidence_omission_reasons,
        "mandatory_semantic_record_count": mandatory_semantic_record_count,
        "estimated_tokens": pack_estimated_tokens,
        "estimated_token_budget": estimated_token_budget,
        "prior_summary_count": len(prior_summaries),
        "prior_summary_chars": prior_summary_chars,
        "handoff_anchor_count": max(model_pack_handoff_anchor_lines(pack_text), default=0),
        "required_handoff_anchor_groups": required_handoff_anchor_groups(
            max(model_pack_handoff_anchor_lines(pack_text), default=0)
        ),
        "handoff_complete": True,
        "preserve_prior_summaries_verbatim_requested": bool(preserve_prior_summaries_verbatim),
        "session_lineage_compatibility": bool(session_lineage_compatibility),
        "session_lineage_transition_count": int(session_lineage_transition_count),
    }


def build_model_summary_pack_text(
    input_path: pathlib.Path,
    records: Sequence[JsonObj],
    raw_lines: Sequence[str],
    omitted_indexes: Sequence[int],
    kept_count: int,
    source_digest: str,
    omitted_digest: str,
    preserve_mode: str,
    selected_leaf_uuid: Optional[str],
    char_budget: int,
    handoff_summary_text: Optional[str] = None,
    handoff_summary_digest: Optional[str] = None,
    preserve_prior_summaries_verbatim: bool = False,
    estimated_token_budget: int = DEFAULT_MODEL_PACK_ESTIMATED_TOKEN_BUDGET,
    pack_request_digest: Optional[str] = None,
) -> str:
    del raw_lines
    direct_request_digest = pack_request_digest or canonical_json_sha256({
        "schema": MODEL_PACK_SCHEMA_VERSION,
        "directPackHelper": True,
        "charBudget": char_budget,
        "estimatedTokenBudget": estimated_token_budget,
        "handoffSummarySha256": handoff_summary_digest,
        "preservePriorSummariesVerbatim": bool(preserve_prior_summaries_verbatim),
    })
    return str(build_model_summary_pack_payload(
        input_path=input_path,
        records=records,
        omitted_indexes=omitted_indexes,
        kept_count=kept_count,
        source_digest=source_digest,
        omitted_digest=omitted_digest,
        preserve_mode=preserve_mode,
        selected_leaf_uuid=selected_leaf_uuid,
        char_budget=char_budget,
        pack_request_digest=direct_request_digest,
        handoff_summary_text=handoff_summary_text,
        handoff_summary_digest=handoff_summary_digest,
        preserve_prior_summaries_verbatim=preserve_prior_summaries_verbatim,
        estimated_token_budget=estimated_token_budget,
    )["text"])


def write_model_summary_pack(path: pathlib.Path, pack_text: str) -> None:
    if is_under_claude_root(path):
        raise ValueError("model-summary evidence packs must be outside the entire .claude directory")
    atomic_write_text(path, pack_text)


def make_boundary_record(common: JsonObj, parent_uuid: Optional[str], boundary_uuid: str, summary_uuid: str, first_kept_uuid: Optional[str], metadata: JsonObj) -> JsonObj:
    rec: JsonObj = {}
    if parent_uuid is not None:
        rec["parentUuid"] = parent_uuid
    else:
        rec["parentUuid"] = None
    rec["isSidechain"] = False
    rec["type"] = "system"
    rec["subtype"] = "compact_boundary"
    rec["uuid"] = boundary_uuid
    rec["timestamp"] = now_iso()
    for key, val in common.items():
        rec.setdefault(key, val)
    rec["level"] = "info"
    rec["isMeta"] = True
    rec["content"] = "Codex offline JSONL compression boundary. Early/middle transcript records were summarized; recent raw records are preserved."
    rec["compactMetadata"] = metadata
    return rec


def make_summary_record(common: JsonObj, boundary_uuid: str, summary_uuid: str, summary_text: str) -> JsonObj:
    rec: JsonObj = {
        "parentUuid": boundary_uuid,
        "isSidechain": False,
        "promptId": str(uuid.uuid4()),
        "type": "user",
        "message": {
            "role": "user",
            "content": summary_text,
        },
        "isCompactSummary": True,
        "isVisibleInTranscriptOnly": True,
        "uuid": summary_uuid,
        "timestamp": now_iso(),
    }
    for key, val in common.items():
        rec.setdefault(key, val)
    return rec


def repair_and_preserve_recent(
    kept: Sequence[JsonObj],
    previous_uuid: str,
    previous_session: Optional[str],
    present: set,
    single_resume_chain: bool = False,
) -> Tuple[List[JsonObj], List[JsonObj]]:
    out: List[JsonObj] = []
    repairs: List[JsonObj] = []
    last_uuid = previous_uuid
    last_session = previous_session
    uuid_session: Dict[str, Optional[str]] = {previous_uuid: previous_session}
    known_uuids = set(present)
    for obj in kept:
        uid = obj.get("uuid")
        if isinstance(uid, str) and uid:
            known_uuids.add(uid)
            sess = obj.get("sessionId")
            uuid_session[uid] = str(sess) if isinstance(sess, str) else None

    for original in kept:
        obj = copy.deepcopy(original)
        uid = obj.get("uuid")
        if isinstance(uid, str) and uid:
            parent = obj.get("parentUuid")
            sess_val = obj.get("sessionId")
            session_id = str(sess_val) if isinstance(sess_val, str) else None
            new_parent = parent
            reason = ""
            if parent is None and single_resume_chain and last_uuid:
                new_parent = last_uuid
                reason = "root_relinked_to_previous_for_single_resume_chain"
            elif parent is not None:
                parent_session = uuid_session.get(parent) if isinstance(parent, str) else None
                if parent not in known_uuids:
                    if session_id is not None and last_session is not None and session_id != last_session:
                        if single_resume_chain and last_uuid:
                            new_parent = last_uuid
                            reason = "missing_parent_relinked_for_single_resume_chain"
                        else:
                            new_parent = None
                            reason = "missing_parent_new_session_root"
                    elif last_uuid and (session_id is None or last_session is None or session_id == last_session):
                        new_parent = last_uuid
                        reason = "missing_parent_same_session_relinked"
                    else:
                        new_parent = None
                        reason = "missing_parent_root"
                elif session_id is not None and parent_session is not None and session_id != parent_session:
                    if last_uuid and last_session == session_id:
                        new_parent = last_uuid
                        reason = "cross_session_parent_relinked_to_same_session_previous"
                    elif single_resume_chain and last_uuid:
                        new_parent = last_uuid
                        reason = "cross_session_parent_relinked_for_single_resume_chain"
                    else:
                        new_parent = None
                        reason = "cross_session_parent_new_session_root"
            if new_parent != parent:
                obj["parentUuid"] = new_parent
                repairs.append(
                    {
                        "uuid": uid,
                        "type": obj.get("type"),
                        "sessionId": session_id,
                        "oldParentUuid": parent,
                        "newParentUuid": new_parent,
                        "reason": reason,
                    }
                )
            present.add(uid)
            last_uuid = uid
            last_session = session_id
        out.append(obj)
    return out, repairs


def splice_active_recent(
    kept: Sequence[JsonObj],
    summary_uuid: str,
    summary_session: Optional[str],
) -> Tuple[List[JsonObj], List[JsonObj]]:
    """Attach one validated active suffix to the new compact summary.

    The first parent edge is the only intentional graph rewrite. Every later
    parent edge must already describe the same linear active chain.
    """
    if not kept:
        return [], []
    out: List[JsonObj] = []
    repairs: List[JsonObj] = []
    previous_uuid = summary_uuid
    previous_session = summary_session
    for position, original in enumerate(kept):
        obj = copy.deepcopy(original)
        uid = obj.get("uuid")
        if not isinstance(uid, str) or not uid:
            raise ValueError("strict active-chain raw suffix contains a record without uuid")
        old_parent = obj.get("parentUuid")
        session_id = obj.get("sessionId") if isinstance(obj.get("sessionId"), str) else None
        if position == 0:
            obj["parentUuid"] = summary_uuid
            repairs.append(
                {
                    "uuid": uid,
                    "type": obj.get("type"),
                    "sessionId": session_id,
                    "oldParentUuid": old_parent,
                    "newParentUuid": summary_uuid,
                    "reason": "compression_cut_spliced_to_compact_summary",
                }
            )
        elif old_parent != previous_uuid:
            raise ValueError(
                f"strict active-chain suffix has an unexpected parent at position {position + 1}: "
                f"expected {previous_uuid}, found {old_parent}"
            )
        if (
            isinstance(previous_session, str)
            and isinstance(session_id, str)
            and previous_session != session_id
        ):
            raise ValueError("strict active-chain suffix crosses sessionId boundaries")
        out.append(obj)
        previous_uuid = uid
        previous_session = session_id or previous_session
    return out, repairs


def update_last_prompt(records: List[JsonObj]) -> int:
    uuid_set = {obj.get("uuid") for obj in records if isinstance(obj.get("uuid"), str)}
    leaf = None
    for obj in reversed(records):
        uid = obj.get("uuid")
        if isinstance(uid, str) and uid:
            leaf = uid
            break
    if not leaf:
        return 0
    changed = 0
    for obj in records:
        if obj.get("type") == "last-prompt" and obj.get("leafUuid") not in uuid_set:
            obj["leafUuid"] = leaf
            changed += 1
    return changed


def normalize_session_ids(records: Sequence[JsonObj], target_session_id: str) -> int:
    changed = 0
    for obj in records:
        if isinstance(obj.get("sessionId"), str) and obj.get("sessionId") != target_session_id:
            obj["sessionId"] = target_session_id
            changed += 1
    return changed


def append_final_last_prompt(records: List[JsonObj], target_session_id: Optional[str] = None) -> int:
    leaf = None
    leaf_session = target_session_id
    for obj in reversed(records):
        uid = obj.get("uuid")
        if isinstance(uid, str) and uid:
            leaf = uid
            if leaf_session is None and isinstance(obj.get("sessionId"), str):
                leaf_session = obj.get("sessionId")
            break
    if not leaf:
        return 0
    if records and records[-1].get("type") == "last-prompt":
        current_session = records[-1].get("sessionId")
        if records[-1].get("leafUuid") == leaf and (leaf_session is None or current_session == leaf_session):
            return 0
    rec: JsonObj = {"type": "last-prompt", "leafUuid": leaf}
    if leaf_session:
        rec["sessionId"] = leaf_session
    records.append(rec)
    return 1


def append_projected_last_prompt(
    records: List[JsonObj],
    source_template: Optional[JsonObj],
    target_session_id: Optional[str] = None,
) -> int:
    """Append exactly one final pointer while retaining unknown source fields."""
    records[:] = [obj for obj in records if obj.get("type") != "last-prompt"]
    leaf_record = next(
        (obj for obj in reversed(records) if isinstance(obj.get("uuid"), str) and obj.get("uuid")),
        None,
    )
    if leaf_record is None:
        return 0
    projected = copy.deepcopy(source_template) if isinstance(source_template, dict) else {"type": "last-prompt"}
    projected["type"] = "last-prompt"
    projected["leafUuid"] = leaf_record.get("uuid")
    leaf_session = leaf_record.get("sessionId") if isinstance(leaf_record.get("sessionId"), str) else None
    if target_session_id:
        projected["sessionId"] = target_session_id
    elif leaf_session and "sessionId" in projected:
        projected["sessionId"] = leaf_session
    records.append(projected)
    return 1


def active_chain_uuids_to_anchor(records: Sequence[JsonObj], anchor_uuid: str) -> List[str]:
    uuid_to_record = {obj.get("uuid"): obj for obj in records if isinstance(obj.get("uuid"), str)}
    leaf: Optional[str] = None
    for obj in reversed(records):
        if obj.get("type") == "last-prompt" and isinstance(obj.get("leafUuid"), str):
            leaf = obj.get("leafUuid")
            break
    if leaf is None:
        for obj in reversed(records):
            uid = obj.get("uuid")
            if isinstance(uid, str) and uid:
                leaf = uid
                break
    if leaf is None:
        return []
    chain: List[str] = []
    seen: set = set()
    cur: Optional[str] = leaf
    while cur:
        if cur in seen:
            return []
        seen.add(cur)
        obj = uuid_to_record.get(cur)
        if obj is None:
            return []
        if cur == anchor_uuid:
            chain.reverse()
            return chain
        chain.append(cur)
        parent = obj.get("parentUuid")
        cur = parent if isinstance(parent, str) else None
    return []


def update_compact_preserved_metadata(records: List[JsonObj], boundary_uuid: str, summary_uuid: str) -> int:
    preserved_uuids = active_chain_uuids_to_anchor(records, summary_uuid)
    if not preserved_uuids:
        return 0
    summary_index = next(
        (idx for idx, obj in enumerate(records) if obj.get("uuid") == summary_uuid),
        None,
    )
    if summary_index is None:
        return 0
    all_uuids = [
        obj.get("uuid")
        for obj in records[summary_index + 1 :]
        if isinstance(obj.get("uuid"), str)
    ]
    changed = 0
    for obj in records:
        if obj.get("uuid") != boundary_uuid or obj.get("type") != "system" or obj.get("subtype") != "compact_boundary":
            continue
        metadata = obj.setdefault("compactMetadata", {})
        if not isinstance(metadata, dict):
            metadata = {}
            obj["compactMetadata"] = metadata
        metadata["preservedSegment"] = {
            "headUuid": preserved_uuids[0],
            "anchorUuid": summary_uuid,
            "tailUuid": preserved_uuids[-1],
        }
        metadata["preservedMessages"] = {
            "anchorUuid": summary_uuid,
            "uuids": preserved_uuids,
            "allUuids": all_uuids,
        }
        changed += 1
    return changed


def summarize_active_chain_window(records: Sequence[JsonObj], summary_uuid: str) -> Dict[str, Any]:
    latest_leaf = latest_last_prompt_leaf(records) or latest_physical_uuid(records)
    trace = chain_trace_from_leaf(records, latest_leaf)
    chain = list(trace.get("chain") or [])
    if not chain:
        return {
            "leafUuid": latest_leaf,
            "chainLength": 0,
            "missingUuid": trace.get("missingUuid"),
            "loopUuid": trace.get("loopUuid"),
            "boundaryUuid": None,
            "summaryUuid": summary_uuid,
            "firstRecentUuid": None,
            "lastUuid": None,
            "sessionCounts": {},
            "typeCounts": {},
        }
    uuids = [obj.get("uuid") for obj in chain if isinstance(obj.get("uuid"), str)]
    summary_pos = next((idx for idx, obj in enumerate(chain) if obj.get("uuid") == summary_uuid), None)
    after_summary = chain[summary_pos + 1 :] if isinstance(summary_pos, int) else []
    session_counts = collections.Counter(obj.get("sessionId", "<missing>") for obj in chain)
    type_counts = collections.Counter(obj.get("type", "<missing>") for obj in chain)
    return {
        "leafUuid": latest_leaf,
        "chainLength": len(chain),
        "missingUuid": trace.get("missingUuid"),
        "loopUuid": trace.get("loopUuid"),
        "boundaryUuid": next((obj.get("uuid") for obj in chain if obj.get("type") == "system" and obj.get("subtype") == "compact_boundary"), None),
        "summaryUuid": summary_uuid,
        "firstRecentUuid": next((obj.get("uuid") for obj in after_summary if isinstance(obj.get("uuid"), str)), None),
        "lastUuid": uuids[-1] if uuids else None,
        "sessionCounts": dict(session_counts.most_common(10)),
        "typeCounts": dict(type_counts.most_common(10)),
    }


def select_preservation_plan(
    records: Sequence[JsonObj],
    raw_lines: Sequence[str],
    input_bytes: int,
    target_ratio: float,
    min_recent_records: int,
    summary_char_budget: int,
    preserve_active_chain: bool,
    max_post_prompt_extension: int,
    max_file_history_snapshots: int,
    checkpoint_policy: str = "active-correlated",
    resume_leaf_override: Optional[str] = None,
) -> Dict[str, Any]:
    summary_budget_bytes = max(4096, summary_char_budget * 3 + 20000)
    preserve_info: Optional[Dict[str, Any]] = None
    file_history_snapshots_original: List[JsonObj] = []
    file_history_snapshot_indexes: List[int] = []
    if preserve_active_chain:
        preserve_info = choose_active_chain_preservation(
            records,
            raw_lines,
            input_bytes,
            target_ratio,
            min_recent_records,
            summary_budget_bytes,
            max_post_prompt_extension,
            max_file_history_snapshots,
            checkpoint_policy,
            resume_leaf_override,
        )
        if preserve_info is None:
            raise ValueError("strict active-chain topology selected no chain")
    if not preserve_active_chain:
        start = choose_recent_start(records, raw_lines, input_bytes, target_ratio, min_recent_records, summary_budget_bytes)
        adjusted_start = adjust_recent_start_for_tool_pairs(records, start)
        start = adjusted_start
        if start <= 0:
            raise ValueError("input is too small to compress with the requested settings")
        omitted = records[:start]
        kept_original = records[start:]
        omitted_indexes = list(range(start))
        recent_start_record = start + 1
        recent_end_record = len(records)
        preserve_mode = "physical-tail"
        selected_leaf_uuid = latest_physical_uuid(kept_original)
        source_active_chain_length = None
        active_chain_start_position = None
        prior_compact_record_count = None
        prior_compact_last_position = None
        summary_indexes = list(omitted_indexes)
        raw_keep_indexes = list(range(start, len(records)))
        side_keep_indexes: List[int] = []
        control_projection_indexes: List[int] = []
        excluded_branch_indexes: List[int] = []
        excluded_unattributed_indexes: List[int] = []
        last_prompt_template = copy.deepcopy(latest_last_prompt_entry(records)[1]) if latest_last_prompt_entry(records) else None
    else:
        omitted = list(preserve_info["omitted"])
        kept_original = list(preserve_info["kept"])
        file_history_snapshots_original = list(preserve_info.get("fileHistorySnapshots") or [])
        file_history_snapshot_indexes = list(preserve_info.get("fileHistorySnapshotIndexes") or [])
        omitted_indexes = list(preserve_info["omittedIndexes"])
        recent_start_record = preserve_info["recentStartRecord"]
        recent_end_record = preserve_info["recentEndRecord"]
        preserve_mode = str(preserve_info["mode"])
        selected_leaf_uuid = preserve_info.get("leafUuid")
        source_active_chain_length = preserve_info.get("sourceActiveChainLength")
        active_chain_start_position = preserve_info.get("activeChainStartPosition")
        prior_compact_record_count = preserve_info.get("priorCompactRecordCountInActiveChain")
        prior_compact_last_position = preserve_info.get("priorCompactLastPositionInActiveChain")
        session_lineage_compatibility = bool(preserve_info.get("sessionLineageCompatibility"))
        session_lineage_transition_count = int(preserve_info.get("sessionLineageTransitionCount") or 0)
        session_lineage_forced_start = bool(preserve_info.get("sessionLineageForcedStart"))
        start = (recent_start_record - 1) if isinstance(recent_start_record, int) else len(records)
        if not kept_original:
            raise ValueError("active-chain preservation selected no records")
        summary_indexes = list(preserve_info.get("summaryIndexes") or [])
        raw_keep_indexes = list(preserve_info.get("rawKeepIndexes") or [])
        side_keep_indexes = list(preserve_info.get("sideKeepIndexes") or [])
        control_projection_indexes = list(preserve_info.get("controlProjectionIndexes") or [])
        excluded_branch_indexes = list(preserve_info.get("excludedBranchIndexes") or [])
        excluded_unattributed_indexes = list(preserve_info.get("excludedUnattributedIndexes") or [])
        last_prompt_template = copy.deepcopy(preserve_info.get("lastPromptTemplate"))
        if not summary_indexes:
            raise ValueError("active resume chain has no old records to summarize with the requested settings")
    return {
        "preserve_info": preserve_info,
        "omitted": list(omitted),
        "kept_original": list(kept_original),
        "file_history_snapshots_original": list(file_history_snapshots_original),
        "file_history_snapshot_indexes": list(file_history_snapshot_indexes),
        "omitted_indexes": list(omitted_indexes),
        "summary_indexes": summary_indexes,
        "raw_keep_indexes": raw_keep_indexes,
        "side_keep_indexes": side_keep_indexes,
        "control_projection_indexes": control_projection_indexes,
        "excluded_branch_indexes": excluded_branch_indexes,
        "excluded_unattributed_indexes": excluded_unattributed_indexes,
        "last_prompt_template": last_prompt_template,
        "checkpoint_policy": checkpoint_policy if preserve_active_chain else "physical-tail-compatibility",
        "recent_start_record": recent_start_record,
        "recent_end_record": recent_end_record,
        "preserve_mode": preserve_mode,
        "selected_leaf_uuid": selected_leaf_uuid,
        "source_active_chain_length": source_active_chain_length,
        "active_chain_start_position": active_chain_start_position,
        "prior_compact_record_count": prior_compact_record_count,
        "prior_compact_last_position": prior_compact_last_position,
        "session_lineage_compatibility": session_lineage_compatibility if preserve_active_chain else False,
        "session_lineage_transition_count": session_lineage_transition_count if preserve_active_chain else 0,
        "session_lineage_forced_start": session_lineage_forced_start if preserve_active_chain else False,
        "start": start,
    }


def validate_source_active_chain_for_plan(
    records: Sequence[JsonObj],
    plan: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Validate the authoritative logical chain without inspecting inactive branches."""
    preserve_info = plan.get("preserve_info")
    if not isinstance(preserve_info, dict):
        return None
    resume_info = preserve_info.get("resumeLeafInfo")
    if not isinstance(resume_info, dict):
        raise ValueError("source active-chain validation failed: preservation plan lacks resume topology")
    active_indexes = list(resume_info.get("activeChainIndexes") or [])
    if not active_indexes:
        raise ValueError("source active-chain validation failed: authoritative chain is empty")
    active_records = [copy.deepcopy(records[int(idx)]) for idx in active_indexes]
    selected_leaf = plan.get("selected_leaf_uuid")
    if not isinstance(selected_leaf, str) or not selected_leaf:
        raise ValueError("source active-chain validation failed: selected leaf is missing")
    leaf_record = next(
        (obj for obj in reversed(active_records) if obj.get("uuid") == selected_leaf),
        None,
    )
    if leaf_record is None:
        raise ValueError("source active-chain validation failed: selected leaf is absent from the logical chain")
    pointer = copy.deepcopy(plan.get("last_prompt_template"))
    if not isinstance(pointer, dict):
        pointer = {"type": "last-prompt"}
    pointer["type"] = "last-prompt"
    pointer["leafUuid"] = selected_leaf
    leaf_session = leaf_record.get("sessionId")
    if isinstance(leaf_session, str) and leaf_session:
        pointer["sessionId"] = leaf_session
    active_records.append(pointer)
    validation = validate_records(active_records)
    if not validation.get("ok"):
        raise ValueError(
            "source active-chain validation failed: "
            + "; ".join(str(error) for error in validation.get("errors") or ["unknown validation error"])
        )
    return validation


def build_model_summary_pack_for_input(
    input_path: pathlib.Path,
    target_ratio: float,
    min_recent_records: int,
    summary_char_budget: int,
    preserve_active_chain: bool = True,
    max_post_prompt_extension: int = 0,
    max_file_history_snapshots: int = 80,
    checkpoint_policy: str = "active-correlated",
    resume_leaf_override: Optional[str] = None,
    model_pack_char_budget: int = 500000,
    model_pack_estimated_token_budget: int = DEFAULT_MODEL_PACK_ESTIMATED_TOKEN_BUDGET,
    handoff_summary_path: Optional[pathlib.Path] = None,
    preserve_prior_summaries_verbatim: bool = False,
    target_estimated_tokens: Optional[int] = None,
) -> Dict[str, Any]:
    require_summary_char_budget(summary_char_budget)
    if min_recent_records < 0:
        raise ValueError("min_recent_records must be non-negative")
    if handoff_summary_path is not None and is_under_claude_root(handoff_summary_path):
        raise ValueError("--handoff-summary process files must be outside the entire .claude directory")
    source_bytes = input_path.read_bytes()
    records, raw_lines = parse_jsonl_bytes(source_bytes, source_label=str(input_path))
    if not records:
        raise ValueError("input JSONL has no records")
    input_bytes = len(source_bytes)
    effective_target_ratio, input_estimated_tokens = effective_target_ratio_for_tokens(
        records, target_ratio, target_estimated_tokens
    )
    plan = select_preservation_plan(
        records,
        raw_lines,
        input_bytes,
        effective_target_ratio,
        min_recent_records,
        summary_char_budget,
        preserve_active_chain,
        max_post_prompt_extension,
        max_file_history_snapshots,
        checkpoint_policy,
        resume_leaf_override,
    )
    source_active_chain_validation = validate_source_active_chain_for_plan(records, plan)
    source_sha256 = sha256_hex(source_bytes)
    source_digest = source_sha256
    omitted_digest = sha256_hex("\n".join(raw_lines[idx] for idx in plan["omitted_indexes"]).encode("utf-8"))
    handoff_text, handoff_digest, handoff_bytes = read_optional_text(handoff_summary_path)
    _pack_request_manifest, pack_request_digest = build_pack_request_manifest(
        target_ratio=target_ratio,
        min_recent_records=min_recent_records,
        summary_char_budget=summary_char_budget,
        preserve_active_chain=preserve_active_chain,
        max_post_prompt_extension=max_post_prompt_extension,
        max_file_history_snapshots=max_file_history_snapshots,
        checkpoint_policy=checkpoint_policy,
        resume_leaf_override=resume_leaf_override,
        model_pack_char_budget=model_pack_char_budget,
        model_pack_estimated_token_budget=model_pack_estimated_token_budget,
        preserve_prior_summaries_verbatim=preserve_prior_summaries_verbatim,
        target_estimated_tokens=target_estimated_tokens,
        handoff_summary_sha256=handoff_digest,
    )
    pack = build_model_summary_pack_payload(
        input_path=input_path,
        records=records,
        omitted_indexes=plan["omitted_indexes"],
        kept_count=len(plan["kept_original"]),
        source_digest=source_digest,
        omitted_digest=omitted_digest,
        preserve_mode=plan["preserve_mode"],
        selected_leaf_uuid=plan["selected_leaf_uuid"],
        char_budget=model_pack_char_budget,
        pack_request_digest=pack_request_digest,
        handoff_summary_text=handoff_text or None,
        handoff_summary_digest=handoff_digest,
        preserve_prior_summaries_verbatim=preserve_prior_summaries_verbatim,
        session_lineage_compatibility=bool(plan["session_lineage_compatibility"]),
        session_lineage_transition_count=int(plan["session_lineage_transition_count"]),
        estimated_token_budget=model_pack_estimated_token_budget,
    )
    pack_text = str(pack["text"])
    evidence_anchor_lines = list(pack["evidence_anchor_lines"])
    evidence_anchor_lines_digest = str(pack["evidence_anchor_lines_digest"])
    required_anchor_groups = dict(pack["required_anchor_groups"])
    required_anchor_groups_digest = str(pack["required_anchor_groups_digest"])
    return {
        "text": pack_text,
        "source_sha256_prefix": source_sha256[:16],
        "source_sha256": source_sha256,
        "omitted_digest": omitted_digest,
        "summary_source_sha256": omitted_digest,
        "omitted_record_count": len(plan["omitted_indexes"]),
        "recent_record_count": len(plan["kept_original"]),
        "preserve_mode": plan["preserve_mode"],
        "selected_leaf_uuid": plan["selected_leaf_uuid"],
        "pack_chars": len(pack_text),
        "pack_estimated_tokens": int(pack.get("estimated_tokens") or 0),
        "model_pack_estimated_token_budget": int(pack.get("estimated_token_budget") or 0),
        "evidence_truncated": bool(pack.get("evidence_truncated")),
        "evidence_anchor_line_count": len(evidence_anchor_lines),
        "evidence_anchor_lines_digest": evidence_anchor_lines_digest,
        "evidence_anchor_lines": evidence_anchor_lines,
        "required_anchor_groups": required_anchor_groups,
        "required_anchor_groups_digest": required_anchor_groups_digest,
        "pack_request_digest": str(pack["pack_request_digest"]),
        "required_claim_sources": dict(pack.get("required_claim_sources") or {}),
        "required_claim_sources_digest": str(pack["required_claim_sources_digest"]),
        "optional_evidence_omitted_count": int(pack.get("optional_evidence_omitted_count") or 0),
        "optional_evidence_omitted_lines_digest": str(
            pack.get("optional_evidence_omitted_lines_digest") or anchor_lines_digest([])
        ),
        "optional_evidence_omission_reasons": dict(pack.get("optional_evidence_omission_reasons") or {}),
        "required_handoff_anchor_groups": dict(pack.get("required_handoff_anchor_groups") or {}),
        "mandatory_semantic_record_count": int(pack.get("mandatory_semantic_record_count") or 0),
        "handoff_summary_file": anonymous_artifact_label(handoff_summary_path, "HANDOFF_SUMMARY"),
        "handoff_summary_sha256_prefix": handoff_digest,
        "handoff_summary_bytes": handoff_bytes,
        "prior_summary_count": pack.get("prior_summary_count"),
        "prior_summary_chars": pack.get("prior_summary_chars"),
        "preserve_prior_summaries_verbatim_requested": bool(preserve_prior_summaries_verbatim),
        "session_lineage_compatibility": bool(plan["session_lineage_compatibility"]),
        "session_lineage_transition_count": int(plan["session_lineage_transition_count"]),
        "summary_source_lines": [idx + 1 for idx in plan["summary_indexes"]],
        "excluded_branch_count": len(plan["excluded_branch_indexes"]),
        "excluded_unattributed_count": len(plan["excluded_unattributed_indexes"]),
        "checkpoint_policy": plan["checkpoint_policy"],
        "resume_leaf_info": public_resume_leaf_info(plan["preserve_info"].get("resumeLeafInfo")) if plan["preserve_info"] else None,
        "requested_target_ratio": target_ratio,
        "effective_target_ratio": effective_target_ratio,
        "target_estimated_tokens": target_estimated_tokens,
        "input_estimated_message_tokens": input_estimated_tokens,
        "source_active_chain_tool_pair_partial_result_count": int(
            (source_active_chain_validation or {}).get("tool_pair_partial_result_count") or 0
        ),
        "source_active_chain_validation_warnings": list(
            (source_active_chain_validation or {}).get("warnings") or []
        ),
    }


def compress_jsonl(
    input_path: pathlib.Path,
    output_path: pathlib.Path,
    target_ratio: float,
    min_recent_records: int,
    summary_char_budget: int,
    target_session_id: Optional[str] = None,
    single_resume_chain: bool = False,
    append_final_prompt: bool = False,
    preserve_active_chain: bool = True,
    handoff_summary_path: Optional[pathlib.Path] = None,
    model_summary_path: Optional[pathlib.Path] = None,
    deterministic_summary: bool = False,
    model_pack_char_budget: int = 500000,
    model_pack_estimated_token_budget: int = DEFAULT_MODEL_PACK_ESTIMATED_TOKEN_BUDGET,
    max_post_prompt_extension: int = 0,
    max_file_history_snapshots: int = 80,
    preserve_prior_summaries_verbatim: bool = False,
    checkpoint_policy: str = "active-correlated",
    resume_leaf_override: Optional[str] = None,
    target_estimated_tokens: Optional[int] = None,
    write_sidecar_files: bool = True,
) -> Dict[str, Any]:
    require_summary_char_budget(summary_char_budget)
    if min_recent_records < 0:
        raise ValueError("min_recent_records must be non-negative")
    try:
        if input_path.resolve() == output_path.resolve():
            raise ValueError("--input and --output must be different files")
    except FileNotFoundError:
        if input_path.absolute() == output_path.absolute():
            raise ValueError("--input and --output must be different files")
    if is_under_claude_root(output_path):
        raise ValueError("candidate JSONL and sidecars must be outside the entire .claude directory")
    if handoff_summary_path is not None and is_under_claude_root(handoff_summary_path):
        raise ValueError("--handoff-summary process files must be outside the entire .claude directory")
    if model_summary_path is not None and is_under_claude_root(model_summary_path):
        raise ValueError("--model-summary process files must be outside the entire .claude directory")
    if model_summary_path is not None and deterministic_summary:
        raise ValueError("model_summary_path and deterministic_summary=True are mutually exclusive")
    source_bytes = input_path.read_bytes()
    records, raw_lines = parse_jsonl_bytes(source_bytes, source_label=str(input_path))
    if not records:
        raise ValueError("input JSONL has no records")
    input_bytes = len(source_bytes)
    handoff_text, handoff_digest, handoff_bytes = read_optional_text(handoff_summary_path)
    _pack_request_manifest, pack_request_digest = build_pack_request_manifest(
        target_ratio=target_ratio,
        min_recent_records=min_recent_records,
        summary_char_budget=summary_char_budget,
        preserve_active_chain=preserve_active_chain,
        max_post_prompt_extension=max_post_prompt_extension,
        max_file_history_snapshots=max_file_history_snapshots,
        checkpoint_policy=checkpoint_policy,
        resume_leaf_override=resume_leaf_override,
        model_pack_char_budget=model_pack_char_budget,
        model_pack_estimated_token_budget=model_pack_estimated_token_budget,
        preserve_prior_summaries_verbatim=preserve_prior_summaries_verbatim,
        target_estimated_tokens=target_estimated_tokens,
        handoff_summary_sha256=handoff_digest,
    )
    source_sha256 = sha256_hex(source_bytes)
    source_digest = source_sha256
    effective_target_ratio, input_estimated_tokens = effective_target_ratio_for_tokens(
        records, target_ratio, target_estimated_tokens
    )
    plan = select_preservation_plan(
        records,
        raw_lines,
        input_bytes,
        effective_target_ratio,
        min_recent_records,
        summary_char_budget,
        preserve_active_chain,
        max_post_prompt_extension,
        max_file_history_snapshots,
        checkpoint_policy,
        resume_leaf_override,
    )
    source_active_chain_validation = validate_source_active_chain_for_plan(records, plan)
    preserve_info = plan["preserve_info"]
    omitted = list(plan["omitted"])
    kept_original = list(plan["kept_original"])
    file_history_snapshots_original = list(plan["file_history_snapshots_original"])
    file_history_snapshot_indexes = list(plan["file_history_snapshot_indexes"])
    omitted_indexes = list(plan["omitted_indexes"])
    summary_indexes = list(plan["summary_indexes"])
    raw_keep_indexes = list(plan["raw_keep_indexes"])
    side_keep_indexes = list(plan["side_keep_indexes"])
    control_projection_indexes = list(plan["control_projection_indexes"])
    excluded_branch_indexes = list(plan["excluded_branch_indexes"])
    excluded_unattributed_indexes = list(plan["excluded_unattributed_indexes"])
    last_prompt_template = copy.deepcopy(plan["last_prompt_template"])
    checkpoint_policy = str(plan["checkpoint_policy"])
    recent_start_record = plan["recent_start_record"]
    recent_end_record = plan["recent_end_record"]
    preserve_mode = plan["preserve_mode"]
    selected_leaf_uuid = plan["selected_leaf_uuid"]
    source_active_chain_length = plan["source_active_chain_length"]
    active_chain_start_position = plan["active_chain_start_position"]
    prior_compact_record_count = plan["prior_compact_record_count"]
    prior_compact_last_position = plan["prior_compact_last_position"]
    session_lineage_compatibility = bool(plan["session_lineage_compatibility"])
    session_lineage_transition_count = int(plan["session_lineage_transition_count"])
    session_lineage_forced_start = bool(plan["session_lineage_forced_start"])
    start = plan["start"]
    kept = [copy.deepcopy(obj) for obj in kept_original]
    file_history_snapshots = [copy.deepcopy(obj) for obj in file_history_snapshots_original]
    normalized_session_records = 0
    if target_session_id:
        normalized_session_records += normalize_session_ids(kept, target_session_id)
        normalized_session_records += normalize_session_ids(file_history_snapshots, target_session_id)
    effective_single_resume_chain = single_resume_chain or bool(target_session_id)

    common_source = kept if kept else records
    common = common_fields(common_source)
    if target_session_id:
        common["sessionId"] = target_session_id
    elif session_lineage_compatibility and preserve_info:
        current_session_id = preserve_info.get("resumeLeafInfo", {}).get("currentSessionId")
        if isinstance(current_session_id, str) and current_session_id:
            common["sessionId"] = current_session_id
    deterministic_summary_text = make_summary_text(
        omitted,
        kept + file_history_snapshots,
        input_path,
        start,
        len(records),
        summary_char_budget,
        handoff_summary_text=(handoff_text or None) if deterministic_summary else None,
    )
    omitted_text_digest = sha256_hex("\n".join(raw_lines[idx] for idx in omitted_indexes).encode("utf-8"))
    model_summary_validation: Optional[Dict[str, Any]] = None
    model_pack_estimated_tokens: Optional[int] = None
    model_pack_evidence_truncated: Optional[bool] = None
    model_pack_optional_evidence_omitted_count: Optional[int] = None
    model_pack_optional_evidence_omitted_lines_digest: Optional[str] = None
    model_pack_optional_evidence_omission_reasons: Optional[Dict[str, int]] = None
    semantic_summary_mode = "deterministic-fallback"
    summary_text = deterministic_summary_text
    if model_summary_path is None and not deterministic_summary:
        raise ValueError(
            "model-assisted compression requires model_summary_path by default. "
            "Pass deterministic_summary=True only when the user explicitly asked for deterministic fallback."
        )
    if model_summary_path:
        pack_for_validation = build_model_summary_pack_payload(
            input_path=input_path,
            records=records,
            omitted_indexes=omitted_indexes,
            kept_count=len(kept_original),
            source_digest=source_digest,
            omitted_digest=omitted_text_digest,
            preserve_mode=preserve_mode,
            selected_leaf_uuid=selected_leaf_uuid,
            char_budget=model_pack_char_budget,
            pack_request_digest=pack_request_digest,
            handoff_summary_text=handoff_text or None,
            handoff_summary_digest=handoff_digest,
            preserve_prior_summaries_verbatim=preserve_prior_summaries_verbatim,
            session_lineage_compatibility=session_lineage_compatibility,
            session_lineage_transition_count=session_lineage_transition_count,
            estimated_token_budget=model_pack_estimated_token_budget,
        )
        model_pack_estimated_tokens = int(pack_for_validation.get("estimated_tokens") or 0)
        model_pack_evidence_truncated = bool(pack_for_validation.get("evidence_truncated"))
        model_pack_optional_evidence_omitted_count = int(
            pack_for_validation.get("optional_evidence_omitted_count") or 0
        )
        model_pack_optional_evidence_omitted_lines_digest = str(
            pack_for_validation.get("optional_evidence_omitted_lines_digest") or anchor_lines_digest([])
        )
        model_pack_optional_evidence_omission_reasons = dict(
            pack_for_validation.get("optional_evidence_omission_reasons") or {}
        )
        evidence_anchor_lines = list(pack_for_validation["evidence_anchor_lines"])
        evidence_anchor_lines_digest = str(pack_for_validation["evidence_anchor_lines_digest"])
        required_anchor_groups = dict(pack_for_validation["required_anchor_groups"])
        required_anchor_groups_digest = str(pack_for_validation["required_anchor_groups_digest"])
        model_summary_text = model_summary_path.read_bytes().decode("utf-8-sig", errors="strict")
        model_summary_validation = validate_model_summary_text(
            model_summary_text,
            source_digest,
            omitted_text_digest,
            len(records),
            omitted_indexes,
            allowed_anchor_lines=evidence_anchor_lines,
            expected_evidence_anchor_lines_digest=evidence_anchor_lines_digest,
            required_anchor_groups=required_anchor_groups,
            expected_required_anchor_groups_digest=required_anchor_groups_digest,
            expected_handoff_summary_digest=handoff_digest,
            allowed_handoff_anchor_count=int(pack_for_validation.get("handoff_anchor_count") or 0),
            expected_pack_request_digest=pack_request_digest,
            required_claim_sources=dict(pack_for_validation.get("required_claim_sources") or {}),
            expected_required_claim_sources_digest=str(pack_for_validation["required_claim_sources_digest"]),
        )
        if not model_summary_validation.get("ok"):
            raise ValueError(f"model summary validation failed: {model_summary_validation.get('errors')}")
        summary_text = compose_model_assisted_summary(model_summary_text, deterministic_summary_text, summary_char_budget)
        semantic_summary_mode = "model-assisted-v11"
    summary_text, prior_summary_verbatim_policy = apply_prior_summary_verbatim_policy(
        summary_text,
        omitted,
        omitted_indexes,
        summary_char_budget,
        preserve_prior_summaries_verbatim,
    )
    kept_first_uuid = next((obj.get("uuid") for obj in kept if isinstance(obj.get("uuid"), str)), None)
    parent_uuid = None
    boundary_uuid = str(uuid.uuid4())
    summary_uuid = str(uuid.uuid4())
    metadata = {
        "trigger": "manual",
        "custom_instructions": "Codex offline compression: summarize early/middle history; preserve recent raw JSONL tail for rewind.",
        "codexOfflineCompression": True,
        "codexOfflineCompressionVersion": CODEX_OFFLINE_COMPRESSION_VERSION,
        "semanticSummaryMode": semantic_summary_mode,
        "sourceFileLabel": "SOURCE_JSONL",
        "sourceSha256Prefix": source_sha256[:16],
        "sourceSha256": source_sha256,
        "handoffSummaryFileLabel": anonymous_artifact_label(handoff_summary_path, "HANDOFF_SUMMARY"),
        "handoffSummarySha256Prefix": handoff_digest,
        "handoffSummaryBytes": handoff_bytes,
        "modelSummaryFileLabel": anonymous_artifact_label(model_summary_path, "MODEL_SUMMARY"),
        "modelSummaryValidation": model_summary_validation,
        "priorSummaryVerbatimPolicy": prior_summary_verbatim_policy,
        "reportSchemaVersion": REPORT_SCHEMA_VERSION,
        "modelPackSchemaVersion": MODEL_PACK_SCHEMA_VERSION,
        "modelPackRequestDigest": pack_request_digest,
        "modelPackEstimatedTokens": model_pack_estimated_tokens,
        "modelPackEstimatedTokenBudget": model_pack_estimated_token_budget,
        "modelPackEvidenceTruncated": model_pack_evidence_truncated,
        "modelPackOptionalEvidenceOmittedCount": model_pack_optional_evidence_omitted_count,
        "modelPackOptionalEvidenceOmittedLinesDigest": model_pack_optional_evidence_omitted_lines_digest,
        "modelPackOptionalEvidenceOmissionReasons": model_pack_optional_evidence_omission_reasons,
        "sourceActiveChainToolPairPartialResultCount": int(
            (source_active_chain_validation or {}).get("tool_pair_partial_result_count") or 0
        ),
        "sourceActiveChainValidationWarnings": list(
            (source_active_chain_validation or {}).get("warnings") or []
        ),
        "recentRecordStart": recent_start_record,
        "recentRecordEnd": recent_end_record,
        "summarizedRecordCount": len(omitted),
        "summarySourceLinesDigest": stable_digest(",".join(str(idx + 1) for idx in summary_indexes)),
        "recentRecordCount": len(kept),
        "preservedFileHistorySnapshotCount": len(file_history_snapshots),
        "preservedFileHistorySnapshotSourceLines": [idx + 1 for idx in file_history_snapshot_indexes],
        "preservedFileHistorySnapshotPlacement": "side-records-before-compact-pair",
        "maxFileHistorySnapshots": max_file_history_snapshots,
        "checkpointPolicy": checkpoint_policy,
        "omittedDigest": omitted_text_digest,
        "excludedBranchCount": len(excluded_branch_indexes),
        "excludedBranchDigest": stable_digest(",".join(str(idx + 1) for idx in excluded_branch_indexes)),
        "excludedUnattributedCount": len(excluded_unattributed_indexes),
        "excludedUnattributedDigest": stable_digest(",".join(str(idx + 1) for idx in excluded_unattributed_indexes)),
        "preEstimatedTokens": estimate_records_tokens(omitted),
        "postEstimatedTokens": estimate_tokens(summary_text) + estimate_records_tokens(kept + file_history_snapshots),
        "durationMs": 0,
        "targetSessionId": target_session_id,
        "singleResumeChain": effective_single_resume_chain,
        "preserveMode": preserve_mode,
        "selectedLeafUuid": selected_leaf_uuid,
        "resumeLeafInfo": public_resume_leaf_info(preserve_info.get("resumeLeafInfo")) if preserve_info else None,
        "sourceActiveChainLength": source_active_chain_length,
        "activeChainStartPosition": active_chain_start_position,
        "priorCompactRecordCountInActiveChain": prior_compact_record_count if preserve_info else None,
        "priorCompactLastPositionInActiveChain": prior_compact_last_position if preserve_info else None,
        "sessionLineageCompatibility": session_lineage_compatibility,
        "sessionLineageTransitionCount": session_lineage_transition_count,
        "sessionLineageForcedStart": session_lineage_forced_start,
        "codexPreservedSegment": {
            "firstOriginalUuid": next((obj.get("uuid") for obj in records if isinstance(obj.get("uuid"), str)), None),
            "lastOmittedUuid": next((obj.get("uuid") for obj in reversed(omitted) if isinstance(obj.get("uuid"), str)), None),
            "summaryUuid": summary_uuid,
            "firstRecentUuid": kept_first_uuid,
        },
    }
    boundary = make_boundary_record(common, parent_uuid, boundary_uuid, summary_uuid, kept_first_uuid, metadata)
    summary = make_summary_record(common, boundary_uuid, summary_uuid, summary_text)
    present = {boundary_uuid, summary_uuid}
    summary_session = summary.get("sessionId") if isinstance(summary.get("sessionId"), str) else None
    if preserve_active_chain:
        recent_out, parent_repair_details = splice_active_recent(kept, summary_uuid, summary_session)
    else:
        recent_out, parent_repair_details = repair_and_preserve_recent(
            kept, summary_uuid, summary_session, present, effective_single_resume_chain
        )

    # Only project explicitly classified prefix metadata. No physical-window
    # scan is allowed here because it could resurrect an inactive branch.
    safe_prefix: List[JsonObj] = []
    for idx in control_projection_indexes:
        obj = records[idx]
        if obj.get("type") == "last-prompt":
            continue
        safe_obj = copy.deepcopy(obj)
        if target_session_id:
            normalized_session_records += normalize_session_ids([safe_obj], target_session_id)
        safe_prefix.append(safe_obj)
    output_records: List[JsonObj] = safe_prefix + file_history_snapshots + [boundary, summary] + recent_out
    last_prompt_updates = 0
    final_last_prompt_appended = 0
    if append_final_prompt or target_session_id or preserve_active_chain:
        final_last_prompt_appended = append_projected_last_prompt(
            output_records, last_prompt_template, target_session_id
        )
    compact_preserved_metadata_updates = update_compact_preserved_metadata(output_records, boundary_uuid, summary_uuid)
    active_chain_window = summarize_active_chain_window(output_records, summary_uuid)
    output_estimated_tokens = estimate_records_tokens(output_records)
    if target_estimated_tokens is not None and output_estimated_tokens > target_estimated_tokens:
        raise ValueError(
            f"generated candidate is estimated at {output_estimated_tokens} message tokens, above requested "
            f"target {target_estimated_tokens}; reduce --min-recent-records or --summary-char-budget"
        )
    validation = publish_validated_jsonl(output_path, output_records)
    output_bytes = output_path.stat().st_size

    report = {
        "input": public_path_label(input_path),
        "output": public_path_label(output_path),
        "codex_offline_compression_version": CODEX_OFFLINE_COMPRESSION_VERSION,
        "package_version": PACKAGE_VERSION,
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "model_pack_schema_version": MODEL_PACK_SCHEMA_VERSION,
        "model_pack_request_digest": pack_request_digest,
        "model_pack_estimated_tokens": model_pack_estimated_tokens,
        "model_pack_estimated_token_budget": model_pack_estimated_token_budget,
        "model_pack_evidence_truncated": model_pack_evidence_truncated,
        "model_pack_optional_evidence_omitted_count": model_pack_optional_evidence_omitted_count,
        "model_pack_optional_evidence_omitted_lines_digest": model_pack_optional_evidence_omitted_lines_digest,
        "model_pack_optional_evidence_omission_reasons": model_pack_optional_evidence_omission_reasons,
        "source_active_chain_tool_pair_partial_result_count": int(
            (source_active_chain_validation or {}).get("tool_pair_partial_result_count") or 0
        ),
        "source_active_chain_validation_warnings": list(
            (source_active_chain_validation or {}).get("warnings") or []
        ),
        "input_bytes": input_bytes,
        "output_bytes": output_bytes,
        "ratio": output_bytes / input_bytes if input_bytes else None,
        "requested_target_ratio": target_ratio,
        "effective_target_ratio": effective_target_ratio,
        "target_estimated_tokens": target_estimated_tokens,
        "input_estimated_message_tokens": input_estimated_tokens,
        "output_estimated_message_tokens": output_estimated_tokens,
        "input_records": len(records),
        "output_records": len(output_records),
        "omitted_records": len(omitted),
        "summarized_records": len(summary_indexes),
        "summary_source_lines": [idx + 1 for idx in summary_indexes],
        "summary_source_lines_digest": stable_digest(",".join(str(idx + 1) for idx in summary_indexes)),
        "raw_keep_source_lines": [idx + 1 for idx in raw_keep_indexes],
        "side_keep_source_lines": [idx + 1 for idx in side_keep_indexes],
        "control_projection_source_lines": [idx + 1 for idx in control_projection_indexes],
        "excluded_branch_count": len(excluded_branch_indexes),
        "excluded_branch_source_lines_digest": stable_digest(",".join(str(idx + 1) for idx in excluded_branch_indexes)),
        "excluded_unattributed_count": len(excluded_unattributed_indexes),
        "excluded_unattributed_source_lines_digest": stable_digest(",".join(str(idx + 1) for idx in excluded_unattributed_indexes)),
        "recent_start_record": recent_start_record,
        "recent_end_record": recent_end_record,
        "recent_records_preserved": len(kept),
        "file_history_snapshots_preserved": len(file_history_snapshots),
        "file_history_snapshot_source_lines": [idx + 1 for idx in file_history_snapshot_indexes],
        "checkpoint_policy": checkpoint_policy,
        "preserve_mode": preserve_mode,
        "selected_leaf_uuid": selected_leaf_uuid,
        "source_active_chain_length": source_active_chain_length,
        "active_chain_start_position": active_chain_start_position,
        "prior_compact_record_count_in_active_chain": prior_compact_record_count if preserve_info else None,
        "prior_compact_last_position_in_active_chain": prior_compact_last_position if preserve_info else None,
        "session_lineage_compatibility": session_lineage_compatibility,
        "session_lineage_transition_count": session_lineage_transition_count,
        "session_lineage_forced_start": session_lineage_forced_start,
        "resume_leaf_info": public_resume_leaf_info(preserve_info.get("resumeLeafInfo")) if preserve_info else None,
        "handoff_summary_file": public_path_label(handoff_summary_path),
        "handoff_summary_sha256_prefix": handoff_digest,
        "handoff_summary_bytes": handoff_bytes,
        "semantic_summary_mode": semantic_summary_mode,
        "model_summary_file": public_path_label(model_summary_path),
        "model_summary_validation": model_summary_validation,
        "prior_summary_verbatim_policy": prior_summary_verbatim_policy,
        "source_sha256_prefix": source_sha256[:16],
        "source_sha256": source_sha256,
        "omitted_digest": omitted_text_digest,
        "safe_prefix_records": len(safe_prefix),
        "parent_repairs": len(parent_repair_details),
        "parent_repair_details": parent_repair_details,
        "last_prompt_updates": last_prompt_updates,
        "target_session_id": target_session_id,
        "normalized_session_records": normalized_session_records,
        "single_resume_chain": effective_single_resume_chain,
        "final_last_prompt_appended": final_last_prompt_appended,
        "compact_preserved_metadata_updates": compact_preserved_metadata_updates,
        "active_chain_window": active_chain_window,
        "summary_chars": len(summary_text),
        "boundary_uuid": boundary_uuid,
        "summary_uuid": summary_uuid,
        "first_recent_uuid": kept_first_uuid,
        "validation": validation,
    }
    if write_sidecar_files:
        write_sidecars(output_path, report)
    return report


def validate_records(records: Sequence[JsonObj]) -> Dict[str, Any]:
    errors: List[str] = []
    warnings: List[str] = []
    uuid_counts = collections.Counter(obj.get("uuid") for obj in records if isinstance(obj.get("uuid"), str))
    duplicates = sorted(k for k, v in uuid_counts.items() if v > 1)
    if duplicates:
        errors.append(f"duplicate UUIDs: {duplicates[:20]}")
    uuid_set = set(uuid_counts)
    uuid_to_record = {obj.get("uuid"): obj for obj in records if isinstance(obj.get("uuid"), str)}
    uuid_to_line = {obj.get("uuid"): idx for idx, obj in enumerate(records, 1) if isinstance(obj.get("uuid"), str)}
    missing_parent: List[Tuple[int, str]] = []
    malformed_parent: List[JsonObj] = []
    cross_session_parent: List[JsonObj] = []
    for idx, obj in enumerate(records, 1):
        parent = obj.get("parentUuid")
        if parent is None:
            continue
        if not isinstance(parent, str) or not parent:
            malformed_parent.append(
                {
                    "line": idx,
                    "uuid": obj.get("uuid"),
                    "type": obj.get("type"),
                    "parentUuidType": type(parent).__name__,
                }
            )
            continue
        if parent not in uuid_set:
            missing_parent.append((idx, str(parent)))
        else:
            parent_obj = uuid_to_record.get(parent)
            child_session = obj.get("sessionId")
            parent_session = parent_obj.get("sessionId") if isinstance(parent_obj, dict) else None
            if isinstance(child_session, str) and isinstance(parent_session, str) and child_session != parent_session:
                cross_session_parent.append(
                    {
                        "line": idx,
                        "uuid": obj.get("uuid"),
                        "type": obj.get("type"),
                        "sessionId": child_session,
                        "parentUuid": parent,
                        "parentSessionId": parent_session,
                    }
                )
    if malformed_parent:
        errors.append(f"malformed parentUuid values: {malformed_parent[:30]}")
    if missing_parent:
        errors.append(f"missing parentUuid references: {missing_parent[:30]}")
    last_prompt_records = [
        (idx, obj) for idx, obj in enumerate(records, 1) if obj.get("type") == "last-prompt"
    ]
    last_prompt_malformed: List[JsonObj] = []
    last_prompt_missing: List[JsonObj] = []
    last_prompt_cross_session: List[JsonObj] = []
    for idx, obj in last_prompt_records:
        leaf = obj.get("leafUuid")
        if not isinstance(leaf, str) or not leaf:
            last_prompt_malformed.append(
                {"line": idx, "leafUuidType": type(leaf).__name__, "sessionId": obj.get("sessionId")}
            )
            continue
        target = uuid_to_record.get(leaf)
        if target is None:
            last_prompt_missing.append({"line": idx, "leafUuid": leaf, "sessionId": obj.get("sessionId")})
            continue
        lp_session = obj.get("sessionId")
        target_session = target.get("sessionId")
        if isinstance(lp_session, str) and isinstance(target_session, str) and lp_session != target_session:
            last_prompt_cross_session.append(
                {
                    "line": idx,
                    "leafUuid": leaf,
                    "sessionId": lp_session,
                    "leafSessionId": target_session,
                }
            )
    if last_prompt_missing:
        errors.append(f"last-prompt leafUuid missing targets: {last_prompt_missing[:20]}")
    if last_prompt_cross_session:
        errors.append(f"last-prompt leafUuid cross-session targets: {last_prompt_cross_session[:20]}")
    physical_last_prompt = latest_last_prompt_entry(records)
    physical_last_prompt_line = physical_last_prompt[0] + 1 if physical_last_prompt else None
    physical_last_prompt_malformed = bool(
        physical_last_prompt
        and (not isinstance(physical_last_prompt[1].get("leafUuid"), str) or not physical_last_prompt[1].get("leafUuid"))
    )
    if physical_last_prompt_malformed:
        errors.append(
            "physically last last-prompt leafUuid is missing or malformed; an older pointer is not authoritative"
        )
    elif last_prompt_malformed:
        warnings.append(f"earlier malformed last-prompt records: {last_prompt_malformed[:20]}")
    api_messages = active_api_messages_for_validation(records)
    tool_pair_errors: List[JsonObj] = []
    tool_pair_partial_result_count = 0
    tool_use_occurrences: Dict[str, List[int]] = collections.defaultdict(list)
    tool_result_occurrences: Dict[str, List[int]] = collections.defaultdict(list)
    malformed_tool_id_samples: List[JsonObj] = []
    for line, api_obj in api_messages:
        for block in content_blocks(api_obj):
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use":
                tool_id = block.get("id")
                if not isinstance(tool_id, str) or not tool_id:
                    malformed_tool_id_samples.append(
                        {"line": line, "kind": "tool_use", "idType": type(tool_id).__name__}
                    )
                else:
                    tool_use_occurrences[tool_id].append(line)
            elif block.get("type") == "tool_result":
                tool_id = block.get("tool_use_id") or block.get("toolUseID")
                if not isinstance(tool_id, str) or not tool_id:
                    malformed_tool_id_samples.append(
                        {"line": line, "kind": "tool_result", "idType": type(tool_id).__name__}
                    )
                else:
                    tool_result_occurrences[tool_id].append(line)
    duplicate_tool_use_ids = {
        tool_id: lines for tool_id, lines in tool_use_occurrences.items() if len(lines) > 1
    }
    duplicate_tool_result_ids = {
        tool_id: lines for tool_id, lines in tool_result_occurrences.items() if len(lines) > 1
    }
    if malformed_tool_id_samples:
        tool_pair_errors.append(
            {"reason": "tool_use/tool_result IDs must be non-empty strings", "samples": malformed_tool_id_samples[:20]}
        )
    if duplicate_tool_use_ids:
        tool_pair_errors.append(
            {"reason": "duplicate tool_use IDs in active API messages", "ids": dict(list(duplicate_tool_use_ids.items())[:20])}
        )
    if duplicate_tool_result_ids:
        tool_pair_errors.append(
            {"reason": "duplicate tool_result IDs in active API messages", "ids": dict(list(duplicate_tool_result_ids.items())[:20])}
        )
    assistant_tool_uses_by_uuid: Dict[str, List[str]] = {}
    for _line, api_obj in api_messages:
        if api_role(api_obj) != "assistant":
            continue
        uses_for_uuid = tool_use_ids(api_obj)
        if not uses_for_uuid:
            continue
        candidate_uuids: List[str] = []
        if isinstance(api_obj.get("uuid"), str):
            candidate_uuids.append(api_obj.get("uuid"))
        for merged_uuid in api_obj.get("_mergedUuids", []):
            if isinstance(merged_uuid, str):
                candidate_uuids.append(merged_uuid)
        for assistant_uuid in candidate_uuids:
            assistant_tool_uses_by_uuid[assistant_uuid] = uses_for_uuid
    for pos, (line, obj) in enumerate(api_messages):
        uses = tool_use_ids(obj)
        results = tool_result_ids(obj)
        if uses:
            if pos + 1 >= len(api_messages):
                tool_pair_errors.append(
                    {"line": line, "uuid": obj.get("uuid"), "reason": "assistant tool_use is final api message", "toolUseIds": uses}
                )
            else:
                next_line, next_obj = api_messages[pos + 1]
                next_results = tool_result_ids(next_obj)
                if api_role(next_obj) != "user":
                    tool_pair_errors.append(
                        {
                            "line": line,
                            "uuid": obj.get("uuid"),
                            "reason": "assistant tool_use not followed by user message",
                            "nextLine": next_line,
                            "nextRole": api_role(next_obj),
                            "toolUseIds": uses,
                        }
                    )
                elif not ordered_subsequence(next_results, uses):
                    tool_pair_errors.append(
                        {
                            "line": line,
                            "uuid": obj.get("uuid"),
                            "reason": "assistant tool_use ids do not contain next user tool_result ids in order",
                            "toolUseIds": uses,
                            "nextLine": next_line,
                            "nextToolResultIds": next_results,
                        }
                    )
                elif next_results != uses:
                    tool_pair_partial_result_count += 1
        if results:
            if pos == 0:
                tool_pair_errors.append(
                    {"line": line, "uuid": obj.get("uuid"), "reason": "user tool_result is first api message", "toolResultIds": results}
                )
            else:
                source_uuid = source_tool_assistant_uuid(obj)
                source_obj = uuid_to_record.get(source_uuid) if isinstance(source_uuid, str) else None
                source_uses = assistant_tool_uses_by_uuid.get(source_uuid or "")
                if source_uses is None:
                    source_uses = tool_use_ids(source_obj) if isinstance(source_obj, dict) else []
                prev_line, prev_obj = api_messages[pos - 1]
                prev_uses = tool_use_ids(prev_obj)
                matches_prev = api_role(prev_obj) == "assistant" and ordered_subsequence(results, prev_uses)
                matches_source = ordered_subsequence(results, source_uses)
                if not matches_prev and not matches_source:
                    tool_pair_errors.append(
                        {
                            "line": line,
                            "uuid": obj.get("uuid"),
                            "reason": "user tool_result ids are not an ordered subset of previous/linked assistant tool_use ids",
                            "toolResultIds": results,
                            "prevLine": prev_line,
                            "prevToolUseIds": prev_uses,
                            "sourceToolAssistantUUID": source_uuid,
                            "sourceToolUseIds": source_uses,
                        }
                    )
            types = [block.get("type") if isinstance(block, dict) else type(block).__name__ for block in content_blocks(obj)]
            if any(kind != "tool_result" for kind in types[: len(results)]):
                tool_pair_errors.append(
                    {
                        "line": line,
                        "uuid": obj.get("uuid"),
                        "reason": "tool_result blocks are not first in user message content",
                        "blockTypes": types[:10],
                    }
                )
    if tool_pair_errors:
        errors.append(f"tool_use/tool_result pairing invalid: {tool_pair_errors[:20]}")
    if tool_pair_partial_result_count:
        warnings.append(
            f"accepted {tool_pair_partial_result_count} partial multi-tool result message(s) under the "
            "ordered-subset branch compatibility rule"
        )
    compact_boundaries = [obj for obj in records if obj.get("type") == "system" and obj.get("subtype") == "compact_boundary"]
    compact_summaries = [obj for obj in records if obj.get("isCompactSummary") is True]
    compact_boundary_uuid_set = {
        obj.get("uuid") for obj in compact_boundaries if isinstance(obj.get("uuid"), str) and obj.get("uuid")
    }
    compact_pair_errors: List[JsonObj] = []
    for boundary in compact_boundaries:
        boundary_uuid = boundary.get("uuid")
        if not isinstance(boundary_uuid, str) or not boundary_uuid:
            compact_pair_errors.append({"reason": "compact_boundary lacks a non-empty uuid"})
            continue
        direct_children = [obj for obj in compact_summaries if obj.get("parentUuid") == boundary_uuid]
        if len(direct_children) != 1:
            compact_pair_errors.append(
                {
                    "uuid": boundary_uuid,
                    "reason": "compact_boundary must have exactly one direct isCompactSummary child",
                    "directSummaryCount": len(direct_children),
                }
            )
    for summary in compact_summaries:
        parent_uuid = summary.get("parentUuid")
        if not isinstance(parent_uuid, str) or parent_uuid not in compact_boundary_uuid_set:
            compact_pair_errors.append(
                {
                    "uuid": summary.get("uuid"),
                    "reason": "isCompactSummary must be a direct child of a compact_boundary",
                    "parentUuid": parent_uuid,
                }
            )
    if compact_pair_errors:
        errors.append(f"compact boundary/summary pairing invalid: {compact_pair_errors[:20]}")
    codex_boundaries = [
        obj
        for obj in compact_boundaries
        if isinstance(obj.get("compactMetadata"), dict) and obj["compactMetadata"].get("codexOfflineCompression") is True
    ]
    codex_current_boundary_uuid: Optional[str] = None
    codex_current_summary_uuid: Optional[str] = None
    compact_metadata_preserved_errors: List[JsonObj] = []
    compact_metadata_historical_reference_warnings: List[JsonObj] = []
    compact_boundary_resume_errors: List[JsonObj] = []
    compact_boundary_resume_samples: List[JsonObj] = []
    compact_current_pair_errors: List[JsonObj] = []
    if codex_boundaries:
        if len(codex_boundaries) != 1:
            compact_current_pair_errors.append(
                {"reason": "expected exactly one Codex-created compact_boundary", "count": len(codex_boundaries)}
            )
        if len(compact_summaries) != 1:
            compact_current_pair_errors.append(
                {"reason": "expected exactly one isCompactSummary in compressed candidate", "count": len(compact_summaries)}
            )
        if len(last_prompt_records) != 1:
            compact_current_pair_errors.append(
                {"reason": "expected exactly one last-prompt in compressed candidate", "count": len(last_prompt_records)}
            )
        current_boundary = codex_boundaries[-1]
        codex_current_boundary_uuid = current_boundary.get("uuid") if isinstance(current_boundary.get("uuid"), str) else None
        paired_summaries = [
            obj for obj in compact_summaries if codex_current_boundary_uuid and obj.get("parentUuid") == codex_current_boundary_uuid
        ]
        if len(paired_summaries) != 1:
            compact_current_pair_errors.append(
                {
                    "reason": "Codex-created compact_boundary must have exactly one direct isCompactSummary child",
                    "boundaryUuid": codex_current_boundary_uuid,
                    "pairedSummaryCount": len(paired_summaries),
                }
            )
        elif isinstance(paired_summaries[0].get("uuid"), str):
            codex_current_summary_uuid = paired_summaries[0].get("uuid")
    for obj in compact_boundaries:
        metadata = obj.get("compactMetadata")
        if not isinstance(metadata, dict):
            errors.append(f"compact_boundary {obj.get('uuid')} lacks compactMetadata object")
            continue
        preserved = metadata.get("preservedMessages") or metadata.get("preserved")
        if preserved is not None:
            if not isinstance(preserved, dict):
                compact_metadata_preserved_errors.append({"uuid": obj.get("uuid"), "reason": "preserved is not object"})
            else:
                uuids = preserved.get("uuids")
                anchor_uuid = preserved.get("anchorUuid")
                if not isinstance(uuids, list):
                    compact_metadata_preserved_errors.append({"uuid": obj.get("uuid"), "reason": "preserved.uuids is not array"})
                else:
                    malformed = [uid for uid in uuids if not isinstance(uid, str) or not uid]
                    missing = [uid for uid in uuids if isinstance(uid, str) and uid and uid not in uuid_set]
                    if malformed:
                        compact_metadata_preserved_errors.append(
                            {"uuid": obj.get("uuid"), "reason": "preserved.uuids contains non-string or empty values"}
                        )
                    if missing:
                        compact_metadata_historical_reference_warnings.append(
                            {"uuid": obj.get("uuid"), "reason": "preserved.uuids missing targets", "missing": missing[:20]}
                        )
                if not isinstance(anchor_uuid, str) or anchor_uuid not in uuid_set:
                    compact_metadata_preserved_errors.append(
                        {"uuid": obj.get("uuid"), "reason": "preserved.anchorUuid missing target", "anchorUuid": anchor_uuid}
                    )
        if metadata.get("preservedSegment") is not None:
            segment = metadata.get("preservedSegment")
            if not isinstance(segment, dict):
                compact_metadata_preserved_errors.append({"uuid": obj.get("uuid"), "reason": "preservedSegment is not object"})
            else:
                for key in ("headUuid", "anchorUuid", "tailUuid"):
                    val = segment.get(key)
                    if not isinstance(val, str) or not val:
                        compact_metadata_preserved_errors.append(
                            {"uuid": obj.get("uuid"), "reason": f"preservedSegment.{key} is not a non-empty string"}
                        )
                    elif val not in uuid_set:
                        target = compact_metadata_preserved_errors if key == "anchorUuid" else compact_metadata_historical_reference_warnings
                        target.append(
                            {"uuid": obj.get("uuid"), "reason": f"preservedSegment.{key} missing target", key: val}
                        )
        elif preserved is None:
            warnings.append(f"compact_boundary {obj.get('uuid')} lacks official preservedMessages/preservedSegment")
        if metadata.get("preserveMode") in {"active-chain", "active-chain-manual-override"}:
            selected_leaf = metadata.get("selectedLeafUuid")
            resume_info = metadata.get("resumeLeafInfo")
            if not isinstance(selected_leaf, str):
                compact_boundary_resume_errors.append(
                    {"uuid": obj.get("uuid"), "reason": "missing selectedLeafUuid for active-chain preserveMode"}
                )
            if not isinstance(resume_info, dict):
                compact_boundary_resume_errors.append(
                    {"uuid": obj.get("uuid"), "reason": "missing resumeLeafInfo for active-chain preserveMode"}
                )
            else:
                prompt_leaf = resume_info.get("promptLeafUuid")
                physical_leaf = resume_info.get("physicalLeafUuid")
                selected_leaf_info = resume_info.get("selectedLeafUuid")
                if selected_leaf_info != selected_leaf:
                    compact_boundary_resume_errors.append(
                        {
                            "uuid": obj.get("uuid"),
                            "reason": "resumeLeafInfo.selectedLeafUuid mismatch",
                            "selectedLeafUuid": selected_leaf,
                            "resumeLeafInfoSelectedLeafUuid": selected_leaf_info,
                        }
                    )
                if prompt_leaf is not None and not isinstance(prompt_leaf, str):
                    compact_boundary_resume_errors.append(
                        {"uuid": obj.get("uuid"), "reason": "resumeLeafInfo.promptLeafUuid not string"}
                    )
                if physical_leaf is not None and not isinstance(physical_leaf, str):
                    compact_boundary_resume_errors.append(
                        {"uuid": obj.get("uuid"), "reason": "resumeLeafInfo.physicalLeafUuid not string"}
                    )
                ext_count = resume_info.get("postLastPromptExtensionRecords")
                ext_reason = resume_info.get("postLastPromptExtensionReasons")
                if ext_count is not None and (not isinstance(ext_count, int) or ext_count < 0):
                    compact_boundary_resume_errors.append(
                        {"uuid": obj.get("uuid"), "reason": "resumeLeafInfo.postLastPromptExtensionRecords invalid"}
                    )
                if ext_reason is not None and not isinstance(ext_reason, list):
                    compact_boundary_resume_errors.append(
                        {"uuid": obj.get("uuid"), "reason": "resumeLeafInfo.postLastPromptExtensionReasons invalid"}
                    )
                compact_boundary_resume_samples.append(
                    {
                        "uuid": obj.get("uuid"),
                        "selectedLeafUuid": selected_leaf,
                        "promptLeafUuid": prompt_leaf,
                        "physicalLeafUuid": physical_leaf,
                        "postLastPromptExtensionRecords": ext_count,
                        "postLastPromptExtensionReasons": ext_reason,
                        "postLastPromptExtensionLimited": resume_info.get("postLastPromptExtensionLimited"),
                    }
                )
    if compact_metadata_preserved_errors:
        errors.append(f"compactMetadata preserved references invalid: {compact_metadata_preserved_errors[:20]}")
    if compact_metadata_historical_reference_warnings:
        warnings.append(
            "compactMetadata historical preserved snapshot references records outside the current projection: "
            f"{len(compact_metadata_historical_reference_warnings)} item(s)"
        )
    if compact_boundary_resume_errors:
        errors.append(f"compact_boundary resume metadata invalid: {compact_boundary_resume_errors[:20]}")
    if compact_current_pair_errors:
        errors.append(f"current compact pair invalid: {compact_current_pair_errors[:20]}")
    for obj in compact_summaries:
        msg = obj.get("message")
        if not (
            isinstance(msg, dict)
            and msg.get("role") == "user"
            and isinstance(msg.get("content"), str)
            and bool(msg.get("content").strip())
        ):
            errors.append(f"isCompactSummary {obj.get('uuid')} lacks non-empty message.role=user/content text")
    if not compact_boundaries:
        warnings.append("no compact_boundary records")
    if not compact_summaries:
        warnings.append("no isCompactSummary records")
    latest_last_prompt_line: Optional[int] = physical_last_prompt_line
    latest_last_prompt_session: Optional[str] = None
    latest_last_prompt_leaf: Optional[str] = None
    if physical_last_prompt:
        pointer = physical_last_prompt[1]
        latest_last_prompt_session = pointer.get("sessionId") if isinstance(pointer.get("sessionId"), str) else None
        leaf = pointer.get("leafUuid")
        latest_last_prompt_leaf = leaf if isinstance(leaf, str) and leaf else None
    active_chain: List[JsonObj] = []
    active_chain_missing_uuid: Optional[str] = None
    active_chain_loop = False
    active_chain_malformed_parent: Optional[JsonObj] = None
    if latest_last_prompt_leaf:
        cur: Optional[str] = latest_last_prompt_leaf
        seen: set = set()
        while cur:
            if cur in seen:
                active_chain_loop = True
                break
            seen.add(cur)
            target = uuid_to_record.get(cur)
            if target is None:
                active_chain_missing_uuid = cur
                break
            active_chain.append(target)
            parent = target.get("parentUuid")
            if parent is None:
                cur = None
            elif isinstance(parent, str) and parent:
                cur = parent
            else:
                active_chain_malformed_parent = {
                    "uuid": target.get("uuid"),
                    "parentUuidType": type(parent).__name__,
                }
                break
    active_chain_lines = [
        uuid_to_line.get(obj.get("uuid"))
        for obj in active_chain
        if isinstance(obj.get("uuid"), str) and uuid_to_line.get(obj.get("uuid")) is not None
    ]
    active_chain_root_to_leaf = list(reversed(active_chain))
    active_order_info = analyze_chain_physical_order(records, active_chain_root_to_leaf)
    active_chain_non_monotonic = not active_order_info["ok"]
    active_session_lineage = analyze_session_lineage(active_chain_root_to_leaf, latest_last_prompt_session)
    active_chain_uuid_values = {
        obj.get("uuid") for obj in active_chain if isinstance(obj.get("uuid"), str)
    }
    active_cross_session_parent_count = sum(
        1 for item in cross_session_parent if item.get("uuid") in active_chain_uuid_values
    )
    excluded_cross_session_parent_count = len(cross_session_parent) - active_cross_session_parent_count
    active_chain_has_compact_boundary = any(
        obj.get("type") == "system" and obj.get("subtype") == "compact_boundary" for obj in active_chain
    )
    active_chain_has_compact_summary = any(obj.get("isCompactSummary") is True for obj in active_chain)
    active_chain_uuid_set = {obj.get("uuid") for obj in active_chain if isinstance(obj.get("uuid"), str)}
    active_chain_sessions = collections.Counter(obj.get("sessionId", "<missing>") for obj in active_chain)
    compact_metadata_chain_mismatch: List[JsonObj] = []
    for boundary in compact_boundaries:
        metadata = boundary.get("compactMetadata")
        if not isinstance(metadata, dict):
            continue
        preserved = metadata.get("preservedMessages")
        if not isinstance(preserved, dict):
            continue
        anchor_uuid = preserved.get("anchorUuid")
        declared = preserved.get("uuids")
        if not isinstance(anchor_uuid, str) or not isinstance(declared, list):
            continue
        before_anchor: List[str] = []
        anchor_seen = False
        for obj in active_chain:
            uid = obj.get("uuid")
            if not isinstance(uid, str):
                continue
            if uid == anchor_uuid:
                anchor_seen = True
                break
            before_anchor.append(uid)
        if not anchor_seen:
            compact_metadata_chain_mismatch.append(
                {"uuid": boundary.get("uuid"), "reason": "preservedMessages.anchorUuid not in latest active chain", "anchorUuid": anchor_uuid}
            )
            continue
        actual = list(reversed(before_anchor))
        declared_is_historical_prefix = len(declared) <= len(actual) and declared == actual[: len(declared)]
        if not declared_is_historical_prefix:
            compact_metadata_chain_mismatch.append(
                {
                    "uuid": boundary.get("uuid"),
                    "reason": "preservedMessages.uuids is not a historical active-chain prefix after anchor",
                    "declaredCount": len(declared),
                    "actualCount": len(actual),
                    "declaredHead": declared[:3],
                    "actualHead": actual[:3],
                    "declaredTail": declared[-3:],
                    "actualTail": actual[-3:],
                }
            )
        segment = metadata.get("preservedSegment")
        if isinstance(segment, dict):
            if not declared:
                compact_metadata_chain_mismatch.append(
                    {
                        "uuid": boundary.get("uuid"),
                        "reason": "preservedSegment requires a non-empty preservedMessages.uuids snapshot",
                        "segment": segment,
                        "anchorUuid": anchor_uuid,
                    }
                )
            elif (
                segment.get("headUuid") != declared[0]
                or segment.get("tailUuid") != declared[-1]
                or segment.get("anchorUuid") != anchor_uuid
            ):
                compact_metadata_chain_mismatch.append(
                    {
                        "uuid": boundary.get("uuid"),
                        "reason": "preservedSegment does not match the preservedMessages historical snapshot",
                        "segment": segment,
                        "declaredHead": declared[0],
                        "declaredTail": declared[-1],
                        "anchorUuid": anchor_uuid,
                    }
                )
    if active_chain_loop:
        errors.append("latest last-prompt active chain has a parentUuid loop")
    if active_chain_missing_uuid:
        errors.append(f"latest last-prompt active chain has missing uuid: {active_chain_missing_uuid}")
    if active_chain_malformed_parent:
        errors.append(
            f"latest last-prompt active chain has malformed parentUuid: {active_chain_malformed_parent}"
        )
    if active_chain_non_monotonic:
        errors.append(
            "latest last-prompt active chain has non-monotonic physical parent edges outside the "
            "same-session attachment compatibility rule"
        )
    elif active_order_info["compatibilityEdgeCount"]:
        warnings.append(
            f"latest active chain uses {active_order_info['compatibilityEdgeCount']} same-session "
            "attachment parent edge(s) out of physical order"
        )
    if not active_session_lineage["ok"]:
        errors.append(
            "latest last-prompt active chain has unsafe session lineage: "
            f"{active_session_lineage['reason']}"
        )
    elif active_session_lineage["compatibility"]:
        warnings.append(
            f"latest active chain uses a one-way session lineage with "
            f"{active_session_lineage['transitionCount']} transition(s)"
        )
    if excluded_cross_session_parent_count:
        warnings.append(
            f"excluded/inactive records contain {excluded_cross_session_parent_count} cross-session parent edge(s)"
        )
    if compact_boundaries and latest_last_prompt_leaf and not active_chain_has_compact_boundary:
        errors.append("latest last-prompt active chain does not include compact_boundary")
    if compact_summaries and latest_last_prompt_leaf and not active_chain_has_compact_summary:
        errors.append("latest last-prompt active chain does not include isCompactSummary")
    if codex_current_boundary_uuid and codex_current_boundary_uuid not in active_chain_uuid_set:
        errors.append(f"latest last-prompt active chain does not include current Codex compact_boundary {codex_current_boundary_uuid}")
    if codex_current_summary_uuid and codex_current_summary_uuid not in active_chain_uuid_set:
        errors.append(f"latest last-prompt active chain does not include current Codex isCompactSummary {codex_current_summary_uuid}")
    if compact_metadata_chain_mismatch:
        warnings.append(
            "compactMetadata historical preserved snapshot diverges from the current active chain: "
            f"{len(compact_metadata_chain_mismatch)} item(s)"
        )
    type_counts = collections.Counter(obj.get("type", "<missing>") for obj in records)
    session_counts = collections.Counter(obj.get("sessionId", "<missing>") for obj in records)
    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "records": len(records),
        "uuid_count": len(uuid_set),
        "duplicate_uuid_count": len(duplicates),
        "malformed_parent_count": len(malformed_parent),
        "malformed_parent_samples": malformed_parent[:20],
        "missing_parent_count": len(missing_parent),
        "cross_session_parent_count": len(cross_session_parent),
        "active_cross_session_parent_count": active_cross_session_parent_count,
        "excluded_cross_session_parent_count": excluded_cross_session_parent_count,
        "active_chain_non_monotonic": active_chain_non_monotonic,
        "active_chain_physical_inversion_count": active_order_info["inversionCount"],
        "active_chain_attachment_compatibility_edge_count": active_order_info["compatibilityEdgeCount"],
        "active_chain_session_lineage_compatibility": active_session_lineage["compatibility"],
        "active_chain_session_lineage_transition_count": active_session_lineage["transitionCount"],
        "active_chain_session_lineage_runs_digest": active_session_lineage["runsDigest"],
        "last_prompt_count": len(last_prompt_records),
        "last_prompt_malformed_count": len(last_prompt_malformed),
        "last_prompt_malformed_samples": last_prompt_malformed[:20],
        "last_prompt_missing_leaf_count": len(last_prompt_missing),
        "last_prompt_cross_session_count": len(last_prompt_cross_session),
        "tool_pair_validation_mode": "active-chain-api-message-ordered-subset-with-explicit-partial-warning",
        "tool_pair_merge_strategy": "merge-assistant-fragments-and-split-tool-result-users",
        "active_api_message_count": len(api_messages),
        "tool_pair_partial_result_count": tool_pair_partial_result_count,
        "duplicate_tool_use_id_count": len(duplicate_tool_use_ids),
        "duplicate_tool_use_id_samples": dict(list(duplicate_tool_use_ids.items())[:20]),
        "duplicate_tool_result_id_count": len(duplicate_tool_result_ids),
        "duplicate_tool_result_id_samples": dict(list(duplicate_tool_result_ids.items())[:20]),
        "malformed_tool_id_count": len(malformed_tool_id_samples),
        "malformed_tool_id_samples": malformed_tool_id_samples[:20],
        "tool_pair_error_count": len(tool_pair_errors),
        "tool_pair_error_samples": tool_pair_errors[:20],
        "compact_boundary_count": len(compact_boundaries),
        "compact_summary_count": len(compact_summaries),
        "compact_pair_error_count": len(compact_pair_errors),
        "compact_pair_error_samples": compact_pair_errors[:20],
        "compact_metadata_preserved_error_count": len(compact_metadata_preserved_errors),
        "compact_metadata_preserved_error_samples": compact_metadata_preserved_errors[:20],
        "compact_metadata_historical_reference_warning_count": len(compact_metadata_historical_reference_warnings),
        "compact_metadata_historical_reference_warning_samples": compact_metadata_historical_reference_warnings[:20],
        "compact_boundary_resume_error_count": len(compact_boundary_resume_errors),
        "compact_boundary_resume_error_samples": compact_boundary_resume_errors[:20],
        "compact_boundary_resume_samples": compact_boundary_resume_samples[:20],
        "compact_current_pair_error_count": len(compact_current_pair_errors),
        "compact_current_pair_error_samples": compact_current_pair_errors[:20],
        "codex_compact_boundary_count": len(codex_boundaries),
        "codex_current_boundary_uuid": codex_current_boundary_uuid,
        "codex_current_summary_uuid": codex_current_summary_uuid,
        "compact_metadata_chain_mismatch_count": len(compact_metadata_chain_mismatch),
        "compact_metadata_chain_mismatch_samples": compact_metadata_chain_mismatch[:20],
        "latest_last_prompt_line": latest_last_prompt_line,
        "latest_last_prompt_session_id": latest_last_prompt_session,
        "latest_last_prompt_leaf_uuid": latest_last_prompt_leaf,
        "active_chain_length": len(active_chain),
        "active_chain_missing_uuid": active_chain_missing_uuid,
        "active_chain_loop": active_chain_loop,
        "active_chain_min_line": min(active_chain_lines) if active_chain_lines else None,
        "active_chain_max_line": max(active_chain_lines) if active_chain_lines else None,
        "active_chain_has_compact_boundary": active_chain_has_compact_boundary,
        "active_chain_has_compact_summary": active_chain_has_compact_summary,
        "active_chain_session_counts": dict(active_chain_sessions.most_common(20)),
        "cross_session_parent_samples": cross_session_parent[:20],
        "last_prompt_missing_leaf_samples": last_prompt_missing[:20],
        "last_prompt_cross_session_samples": last_prompt_cross_session[:20],
        "type_counts": dict(type_counts.most_common()),
        "session_counts": dict(session_counts.most_common(20)),
    }


def validate_jsonl(path: pathlib.Path) -> Dict[str, Any]:
    data = path.read_bytes()
    result = validate_jsonl_bytes(data, source_label=public_path_label(path) or "JSONL")
    result["path"] = public_path_label(path)
    result["bytes"] = len(data)
    return result


def validate_jsonl_bytes(data: bytes, source_label: str = "JSONL") -> Dict[str, Any]:
    records, _ = parse_jsonl_bytes(data, source_label=source_label)
    result = validate_records(records)
    result["path"] = pathlib.Path(source_label).name
    result["bytes"] = len(data)
    result["sha256"] = sha256_hex(data)
    return result


def write_sidecars(output_path: pathlib.Path, report: Dict[str, Any]) -> None:
    validation_path = output_path.with_suffix(output_path.suffix + ".validation.json")
    report_path = output_path.with_suffix(output_path.suffix + ".report.md")
    atomic_write_text(
        validation_path,
        json.dumps(report.get("validation", {}), ensure_ascii=False, indent=2),
    )
    lines = [
        "# Claude JSONL Compression Report",
        "",
        f"- Input: `{report['input']}`",
        f"- Output: `{report['output']}`",
        f"- Package version: {report.get('package_version')}",
        f"- Compression engine: {report.get('codex_offline_compression_version')}",
        f"- Model-pack schema: {report.get('model_pack_schema_version')}",
        f"- Model-pack estimated-token ceiling: {report.get('model_pack_estimated_token_budget')}",
        f"- Generated model-pack estimated tokens: {report.get('model_pack_estimated_tokens') or 'not applicable'}",
        f"- Optional model evidence truncated by pack budgets: {report.get('model_pack_evidence_truncated') if report.get('model_pack_evidence_truncated') is not None else 'not applicable'}",
        f"- Report schema: {report.get('report_schema_version')}",
        f"- Original size: {report['input_bytes']} bytes",
        f"- Compressed size: {report['output_bytes']} bytes",
        f"- Size ratio: {report['ratio']:.2%}",
        f"- Requested target ratio: {report.get('requested_target_ratio')}",
        f"- Effective target ratio: {report.get('effective_target_ratio')}",
        f"- Requested estimated-token ceiling: {report.get('target_estimated_tokens') or 'none'}",
        f"- Estimated input message tokens: {report.get('input_estimated_message_tokens')}",
        f"- Estimated output message tokens: {report.get('output_estimated_message_tokens')}",
        f"- Original records: {report['input_records']}",
        f"- Output records: {report['output_records']}",
        f"- Active-chain records summarized: {report.get('summarized_records')}",
        f"- Summary-source line-set digest: `{report.get('summary_source_lines_digest') or ''}`",
        f"- Recent raw records preserved: {report['recent_records_preserved']}",
        f"- Active-correlated side records preserved: {len(report.get('side_keep_source_lines') or [])}",
        f"- Control records projected: {len(report.get('control_projection_source_lines') or [])}",
        f"- Excluded inactive-branch records: {report.get('excluded_branch_count')}",
        f"- Excluded inactive-branch line-set digest: `{report.get('excluded_branch_source_lines_digest') or ''}`",
        f"- Excluded unattributed records: {report.get('excluded_unattributed_count')}",
        f"- Excluded unattributed line-set digest: `{report.get('excluded_unattributed_source_lines_digest') or ''}`",
        f"- Compatibility safe-prefix records: {report['safe_prefix_records']}",
        f"- Intentional cut-edge parent rewrites: {report['parent_repairs']}",
        f"- last-prompt updates: {report['last_prompt_updates']}",
        f"- Summary characters: {report['summary_chars']}",
        f"- compact_boundary UUID: `{report['boundary_uuid']}`",
        f"- isCompactSummary UUID: `{report['summary_uuid']}`",
        f"- First recent raw UUID: `{report['first_recent_uuid']}`",
        f"- Preserve mode: {report.get('preserve_mode')}",
        f"- One-way session-lineage compatibility: {report.get('session_lineage_compatibility')}",
        f"- Session-lineage transitions summarized: {report.get('session_lineage_transition_count')}",
        f"- Session-lineage cut forced to final session: {report.get('session_lineage_forced_start')}",
        f"- Checkpoint policy: {report.get('checkpoint_policy')}",
        f"- File-history snapshots preserved: {report.get('file_history_snapshots_preserved')}",
        f"- Selected leaf: `{report.get('selected_leaf_uuid')}`",
        f"- Resume info: {json.dumps(report.get('resume_leaf_info'), ensure_ascii=False)}",
        f"- Prior compact records in active chain: {report.get('prior_compact_record_count_in_active_chain')}",
        f"- Prior compact last position in active chain: {report.get('prior_compact_last_position_in_active_chain')}",
        f"- Semantic summary mode: {report.get('semantic_summary_mode')}",
        f"- Prior summary verbatim policy mode: {(report.get('prior_summary_verbatim_policy') or {}).get('mode')}",
        f"- Prior summaries preserved verbatim: {(report.get('prior_summary_verbatim_policy') or {}).get('preservedCount')}",
        f"- Model summary file: {report.get('model_summary_file') or 'none'}",
        f"- Handoff summary: {report.get('handoff_summary_file') or 'none'}",
        f"- Handoff summary hash: `{report.get('handoff_summary_sha256_prefix') or ''}`",
        f"- Source SHA-256: `{report.get('source_sha256') or ''}`",
        f"- Summary-source content SHA-256: `{report.get('omitted_digest') or ''}`",
        f"- Replaced original: {report.get('replace_original') is True}",
        f"- Replacement target: `{report.get('replacement_target') or ''}`",
        f"- Replacement backup: `{report.get('replacement_backup') or ''}`",
        f"- Replacement candidate: `{report.get('replacement_candidate') or ''}`",
        "",
        "## Validation",
        "",
        f"- ok: {report['validation'].get('ok')}",
        f"- errors: {report['validation'].get('errors')}",
        f"- warnings: {report['validation'].get('warnings')}",
        f"- compact_boundary_count: {report['validation'].get('compact_boundary_count')}",
        f"- compact_summary_count: {report['validation'].get('compact_summary_count')}",
        f"- missing_parent_count: {report['validation'].get('missing_parent_count')}",
        f"- cross_session_parent_count: {report['validation'].get('cross_session_parent_count')}",
        f"- last_prompt_missing_leaf_count: {report['validation'].get('last_prompt_missing_leaf_count')}",
        f"- last_prompt_cross_session_count: {report['validation'].get('last_prompt_cross_session_count')}",
        f"- duplicate_uuid_count: {report['validation'].get('duplicate_uuid_count')}",
        f"- tool_pair_validation_mode: {report['validation'].get('tool_pair_validation_mode')}",
        f"- tool_pair_merge_strategy: {report['validation'].get('tool_pair_merge_strategy')}",
        f"- active_api_message_count: {report['validation'].get('active_api_message_count')}",
        f"- tool_pair_partial_result_count: {report['validation'].get('tool_pair_partial_result_count')}",
        f"- tool_pair_error_count: {report['validation'].get('tool_pair_error_count')}",
        f"- compact_boundary_resume_error_count: {report['validation'].get('compact_boundary_resume_error_count')}",
        f"- compact_current_pair_error_count: {report['validation'].get('compact_current_pair_error_count')}",
        f"- replacement_validation_ok: {((report.get('replacement_validation') or {}).get('ok') if report.get('replacement_validation') else 'not applicable')}",
        "",
        "## Model Summary Validation",
        "",
        "```json",
        json.dumps(report.get("model_summary_validation"), ensure_ascii=False, indent=2),
        "```",
        "",
        "## Prior Summary Verbatim Policy",
        "",
        "```json",
        json.dumps(report.get("prior_summary_verbatim_policy"), ensure_ascii=False, indent=2),
        "```",
        "",
        "## Intentional Cut-Edge Rewrite Notes",
        "",
        "In strict active-chain mode, only the compression cut edge is rewritten: the first recent record becomes a child of the new summary, and every later recent parent/session edge must already be coherent. Explicit physical-tail compatibility mode may use the legacy repairs listed below. Cross-session links are not invented unless explicit session normalization/single-chain options require them.",
        "",
        "```json",
        json.dumps(report.get("parent_repair_details", [])[:50], ensure_ascii=False, indent=2),
        "```",
        "",
        "## Interpretation",
        "",
        "This report proves only offline candidate JSONL coherence. It is not an official Anthropic format guarantee and does not prove that Claude CLI will consume the file exactly like official /compact. `compactMetadata.codexOfflineCompression=true` marks the file as a Codex offline compression candidate.",
    ]
    atomic_write_text(report_path, "\n".join(lines) + "\n")


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="claude-jsonl-compressor",
        description="Compress one Claude Code JSONL into a validated compact-summary candidate or replace one closed live session transactionally.",
    )
    parser.add_argument("--version", action="store_true", help="Print public, engine, pack, and report versions")
    parser.add_argument("--input", type=pathlib.Path, help="One source Claude Code session JSONL")
    parser.add_argument("--output", type=pathlib.Path, help="Distinct candidate JSONL path; never use with --replace-original")
    parser.add_argument(
        "--replace-original",
        action="store_true",
        help="For one .claude/projects session JSONL: write and validate a candidate in --work-dir, create a numbered .backup beside --input, then replace --input.",
    )
    parser.add_argument(
        "--confirm-session-closed",
        action="store_true",
        help="Required acknowledgement for --replace-original that Claude Code is closed for this session; this is caller confirmation, not process-lock detection.",
    )
    parser.add_argument(
        "--work-dir",
        type=pathlib.Path,
        help="Work directory for --replace-original candidate, reports, and model pack/summary files. Required with --replace-original.",
    )
    parser.add_argument(
        "--backup-dir",
        type=pathlib.Path,
        help="Optional external directory for --replace-original .backup files. If omitted, the numbered backup is created beside --input.",
    )
    parser.add_argument(
        "--target-ratio",
        type=float,
        default=0.30,
        help="Approximate output byte-ratio planning value in [0.05, 0.95]; default 0.30, not a hard gate",
    )
    parser.add_argument(
        "--target-estimated-tokens",
        type=int,
        help="Optional hard ceiling under the zero-dependency approximate Messages estimate; minimum 1000, excludes system/tools/MCP/skills/runtime context",
    )
    parser.add_argument("--min-recent-records", type=int, default=120, help="Non-negative floor for recent raw active records; default 120")
    parser.add_argument("--summary-char-budget", type=int, default=60000, help="Compact-summary character budget; default 60000, minimum 4000")
    parser.add_argument("--target-session-id", help="Normalize sessionId fields to this Claude session ID for file replacement/resume")
    parser.add_argument("--single-resume-chain", action="store_true", help="Relink preserved roots into one parentUuid chain for Claude resume")
    parser.add_argument("--handoff-summary", type=pathlib.Path, help="Optional external handoff summary markdown to weave into the compact summary")
    parser.add_argument("--model-summary", type=pathlib.Path, help="Validated model-authored semantic summary markdown to embed before the deterministic safety appendix")
    parser.add_argument("--deterministic-summary", action="store_true", help="Explicitly opt out of model-assisted summary and use deterministic template fallback")
    parser.add_argument(
        "--preserve-prior-summaries-verbatim",
        action="store_true",
        help="Repeated-compression opt-in: try to embed prior isCompactSummary contents verbatim in the new single compact summary, allowing up to 1.5x summary-char-budget; fall back to normal folded summary if too large.",
    )
    parser.add_argument("--write-model-pack", type=pathlib.Path, help="Write the active-chain summary-source evidence pack, then exit without a candidate JSONL")
    parser.add_argument("--model-pack-char-budget", type=int, default=500000, help="Evidence-pack character ceiling; default 500000, minimum 10000")
    parser.add_argument(
        "--model-pack-estimated-token-budget",
        type=int,
        default=DEFAULT_MODEL_PACK_ESTIMATED_TOKEN_BUDGET,
        help="Zero-dependency estimated-token ceiling for the model pack; default 150000, minimum 10000",
    )
    parser.add_argument("--summary-template", type=pathlib.Path, help="Optional UTF-8 Markdown template for deterministic fallback")
    parser.add_argument("--importance-words", type=pathlib.Path, help='Optional JSON string array or {"importance_words": [...]}')
    parser.add_argument("--topic-patterns", type=pathlib.Path, help='Optional JSON [{"name": ..., "needles": [...]}] array or {"topics": [...]} object')
    parser.add_argument(
        "--max-post-last-prompt-extension",
        type=int,
        default=0,
        help="Explicit safe closure limit after the authoritative last-prompt; default 0 excludes every post-pointer UUID record",
    )
    parser.add_argument(
        "--max-file-history-snapshots",
        type=int,
        default=80,
        help="Maximum recent UUID-less file-history-snapshot side records to preserve in active-chain mode; set 0 to disable",
    )
    parser.add_argument(
        "--preserve-physical-tail",
        action="store_true",
        help="Explicit compatibility mode: use the physical-file tail without active-branch exclusion guarantees",
    )
    parser.add_argument(
        "--checkpoint-policy",
        choices=("active-correlated", "preserve-recent", "none"),
        default="active-correlated",
        help="UUID-less file-history policy; default keeps only snapshots structurally correlated to recent active records",
    )
    parser.add_argument("--resume-leaf", help="Explicit recovery override for the authoritative last-prompt leafUuid")
    parser.add_argument(
        "--analyze-resume-path",
        action="store_true",
        help="Read and report strict resume topology for --input without generating packs, candidates, sidecars, or backups",
    )
    parser.add_argument("--validate-only", type=pathlib.Path, help="Validate one JSONL and exit without compression writes")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    try:
        if args.version:
            print(json.dumps({
                "packageVersion": PACKAGE_VERSION,
                "engineVersion": CODEX_OFFLINE_COMPRESSION_VERSION,
                "modelPackSchemaVersion": MODEL_PACK_SCHEMA_VERSION,
                "defaultModelPackEstimatedTokenBudget": DEFAULT_MODEL_PACK_ESTIMATED_TOKEN_BUDGET,
                "reportSchemaVersion": REPORT_SCHEMA_VERSION,
            }, ensure_ascii=False, indent=2))
            return 0
        if args.validate_only:
            result = validate_jsonl(args.validate_only)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result.get("ok") else 2
        if args.analyze_resume_path:
            if not args.input:
                raise ValueError("--analyze-resume-path requires --input")
            records, _raw_lines = read_jsonl(args.input)
            result = choose_resume_leaf_info(
                records,
                max_post_prompt_extension=args.max_post_last_prompt_extension,
                resume_leaf_override=args.resume_leaf,
            )
            print(json.dumps(public_resume_leaf_info(result), ensure_ascii=False, indent=2))
            return 0 if result.get("ok") else 2
        if args.replace_original and args.write_model_pack:
            raise ValueError("--replace-original cannot be combined with --write-model-pack")
        if args.replace_original and not args.confirm_session_closed:
            raise ValueError("--replace-original requires --confirm-session-closed before any live-session writes")
        if args.confirm_session_closed and not args.replace_original:
            raise ValueError("--confirm-session-closed is only meaningful with --replace-original")
        if args.replace_original and args.output:
            raise ValueError("--replace-original writes its candidate under --work-dir; do not pass --output")
        if args.replace_original and not args.work_dir:
            raise ValueError("--replace-original requires --work-dir")
        if args.replace_original:
            if not is_under_claude_projects(args.input):
                raise ValueError("--replace-original is only for one .claude/projects session JSONL")
            require_live_session_jsonl(args.input)
        if args.backup_dir and not args.replace_original:
            raise ValueError("--backup-dir requires --replace-original")
        if not args.input or (not args.output and not args.replace_original):
            if not (args.input and args.write_model_pack):
                raise ValueError("--input and --output are required unless --validate-only, --write-model-pack, or --replace-original is used")
        if not (0.05 <= args.target_ratio <= 0.95):
            raise ValueError("--target-ratio must be between 0.05 and 0.95")
        if args.target_estimated_tokens is not None and args.target_estimated_tokens < 1000:
            raise ValueError("--target-estimated-tokens must be at least 1000")
        if args.min_recent_records < 0:
            raise ValueError("--min-recent-records must be non-negative")
        require_summary_char_budget(args.summary_char_budget)
        if args.model_pack_char_budget < 10000:
            raise ValueError("--model-pack-char-budget must be at least 10000")
        if args.model_pack_estimated_token_budget < 10000:
            raise ValueError("--model-pack-estimated-token-budget must be at least 10000")
        if args.max_post_last_prompt_extension < 0:
            raise ValueError("--max-post-last-prompt-extension must be non-negative")
        if args.max_file_history_snapshots < 0:
            raise ValueError("--max-file-history-snapshots must be non-negative")
        if args.model_summary and args.deterministic_summary:
            raise ValueError("--model-summary and --deterministic-summary are mutually exclusive")
        process_paths = [
            ("--output", args.output),
            ("--work-dir", args.work_dir),
            ("--backup-dir", args.backup_dir),
            ("--write-model-pack", args.write_model_pack),
            ("--model-summary", args.model_summary),
            ("--handoff-summary", args.handoff_summary),
        ]
        for label, process_path in process_paths:
            if process_path is not None and is_under_claude_root(process_path):
                raise ValueError(f"{label} process files must be outside the entire .claude directory")
        configure_summary_resources(
            importance_words_path=args.importance_words,
            topic_patterns_path=args.topic_patterns,
            summary_template_path=args.summary_template,
            strict=bool(args.importance_words or args.topic_patterns or args.summary_template),
        )
        if args.write_model_pack:
            pack = build_model_summary_pack_for_input(
                input_path=args.input,
                target_ratio=args.target_ratio,
                min_recent_records=args.min_recent_records,
                summary_char_budget=args.summary_char_budget,
                preserve_active_chain=not args.preserve_physical_tail,
                max_post_prompt_extension=args.max_post_last_prompt_extension,
                max_file_history_snapshots=args.max_file_history_snapshots,
                checkpoint_policy=args.checkpoint_policy,
                resume_leaf_override=args.resume_leaf,
                model_pack_char_budget=args.model_pack_char_budget,
                model_pack_estimated_token_budget=args.model_pack_estimated_token_budget,
                handoff_summary_path=args.handoff_summary,
                preserve_prior_summaries_verbatim=args.preserve_prior_summaries_verbatim,
                target_estimated_tokens=args.target_estimated_tokens,
            )
            write_model_summary_pack(args.write_model_pack, pack["text"])
            out = {
                k: v
                for k, v in pack.items()
                if k not in {"text", "required_claim_sources"}
            }
            out["model_pack_path"] = str(args.write_model_pack)
            print(json.dumps(out, ensure_ascii=False, indent=2))
            return 0
        if not args.model_summary and not args.deterministic_summary:
            raise ValueError(
                "model-assisted default workflow requires --model-summary. First run --write-model-pack, "
                "write a model-authored summary from that pack, then rerun with --model-summary. "
                "Use --deterministic-summary only when the user explicitly asks for fallback."
            )
        output_path = args.output
        target_session_id = args.target_session_id
        replacing_original = False
        backup_path: Optional[pathlib.Path] = None
        if args.replace_original:
            replacing_original = True
            input_claude_root = claude_root_ancestor(args.input)
            if input_claude_root and is_same_or_inside(args.work_dir, input_claude_root):
                raise ValueError("--work-dir for --replace-original must be outside the .claude directory")
            if input_claude_root and args.model_summary and is_same_or_inside(args.model_summary, input_claude_root):
                raise ValueError("--model-summary for --replace-original must be outside the .claude directory")
            if input_claude_root and args.handoff_summary and is_same_or_inside(args.handoff_summary, input_claude_root):
                raise ValueError("--handoff-summary for --replace-original must be outside the .claude directory")
            if input_claude_root and args.backup_dir and is_same_or_inside(args.backup_dir, input_claude_root):
                raise ValueError("--backup-dir for --replace-original must be outside the .claude directory")
            output_path = args.work_dir / f"{args.input.stem}.compressed-candidate.jsonl"
            target_session_id = target_session_id or args.input.stem
        elif args.output and is_under_claude_projects(args.output):
            raise ValueError("writing directly to .claude/projects requires --replace-original so a numbered backup is created")
        report = compress_jsonl(
            input_path=args.input,
            output_path=output_path,
            target_ratio=args.target_ratio,
            min_recent_records=args.min_recent_records,
            summary_char_budget=args.summary_char_budget,
            target_session_id=target_session_id,
            single_resume_chain=args.single_resume_chain,
            append_final_prompt=True,
            preserve_active_chain=not args.preserve_physical_tail,
            handoff_summary_path=args.handoff_summary,
            model_summary_path=args.model_summary,
            deterministic_summary=args.deterministic_summary,
            model_pack_char_budget=args.model_pack_char_budget,
            model_pack_estimated_token_budget=args.model_pack_estimated_token_budget,
            max_post_prompt_extension=args.max_post_last_prompt_extension,
            max_file_history_snapshots=args.max_file_history_snapshots,
            preserve_prior_summaries_verbatim=args.preserve_prior_summaries_verbatim,
            checkpoint_policy=args.checkpoint_policy,
            resume_leaf_override=args.resume_leaf,
            target_estimated_tokens=args.target_estimated_tokens,
            write_sidecar_files=not replacing_original,
        )
        if replacing_original:
            current_source_sha256 = file_sha256(args.input)
            if current_source_sha256 != report.get("source_sha256"):
                raise RuntimeError("input JSONL changed after candidate generation; original file was not replaced")
            replacement = _replace_file_after_validation(
                output_path,
                args.input,
                backup_dir=args.backup_dir,
                expected_source_sha256=str(report.get("source_sha256")),
                expected_candidate_sha256=str((report.get("validation") or {}).get("sha256")),
            )
            backup_path = replacement["backup_path"]
            replaced_validation = replacement["validation"]
            report["replace_original"] = True
            report["replacement_target"] = public_path_label(args.input)
            report["replacement_backup"] = public_path_label(backup_path)
            report["replacement_candidate"] = public_path_label(output_path)
            report["replacement_validation"] = replaced_validation
            report["replacement_candidate_sha256"] = replacement["candidate_sha256"]
            report["replacement_published_sha256"] = replacement["published_sha256"]
            report["replacement_parent_directory_fsync"] = replacement["parent_directory_fsync"]
            try:
                write_sidecars(output_path, report)
            except Exception as report_exc:
                receipt = {
                    "operation_state": "committed-report-failed",
                    "replacement_target": public_path_label(args.input),
                    "replacement_backup": public_path_label(backup_path),
                    "replacement_candidate": public_path_label(output_path),
                    "source_sha256": report.get("source_sha256"),
                    "candidate_sha256": replacement.get("candidate_sha256"),
                    "published_sha256": replacement.get("published_sha256"),
                    "replacement_validation_ok": bool(replaced_validation.get("ok")),
                    "report_error": f"{type(report_exc).__name__}: {report_exc}",
                }
                print(json.dumps(receipt, ensure_ascii=False, indent=2))
                eprint(
                    "ERROR: live replacement committed, but final sidecar/report publication failed: "
                    f"{report_exc}"
                )
                return 3
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["validation"].get("ok") else 2
    except Exception as exc:
        eprint(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
