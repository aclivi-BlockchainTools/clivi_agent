#!/usr/bin/env python3
"""Tests unitaris per a is_node_library().

Executa amb: python3 test_node_library_detection.py
"""
import sys
sys.path.insert(0, __file__.rsplit("/", 1)[0])
from bartolo.detectors.discovery import is_node_library

CASES = [
    # (descripció, pkg_data, esperat)

    # --- Casos library ---
    (
        "Express (files + no script arrencable)",
        {
            "name": "express",
            "files": ["LICENSE", "Readme.md", "index.js", "lib/"],
            "scripts": {"lint": "eslint .", "test": "mocha ...", "test-ci": "nyc npm test"},
        },
        True,
    ),
    (
        "React component library (files + peerDeps + exports)",
        {
            "name": "@acme/ui",
            "files": ["dist/"],
            "peerDependencies": {"react": ">=16"},
            "exports": {".": "./dist/index.js"},
            "scripts": {"build": "tsc", "test": "jest"},
        },
        True,
    ),
    (
        "Paquet ESM amb exports i publishConfig, sense start",
        {
            "name": "my-utils",
            "exports": {"./foo": "./src/foo.js"},
            "publishConfig": {"registry": "https://registry.npmjs.org"},
            "scripts": {"test": "node --test"},
        },
        True,
    ),
    (
        "Plugin amb peerDeps i files, sense script arrencable",
        {
            "name": "vite-plugin-foo",
            "files": ["dist/"],
            "peerDependencies": {"vite": ">=4"},
            "scripts": {"build": "tsc"},
        },
        True,
    ),
    (
        "Paquet amb només files i sense scripts (cas mínim)",
        {
            "name": "bare-lib",
            "files": ["index.js"],
            "scripts": {},
        },
        True,  # files(+2) + no script(+1) = 3
    ),

    # --- Casos app (han de retornar False) ---
    (
        "Next.js app (private + dev + start)",
        {
            "name": "my-app",
            "private": True,
            "scripts": {"dev": "next dev", "build": "next build", "start": "next start"},
        },
        False,
    ),
    (
        "Create React App (private + start + build)",
        {
            "name": "my-cra",
            "private": True,
            "scripts": {"start": "react-scripts start", "build": "react-scripts build", "test": "react-scripts test"},
        },
        False,
    ),
    (
        "Vite app típica (private + dev script)",
        {
            "name": "vite-app",
            "private": True,
            "scripts": {"dev": "vite", "build": "vite build", "preview": "vite preview"},
        },
        False,
    ),
    (
        "Express app (usuari usa express, private, té start)",
        {
            "name": "my-api",
            "private": True,
            "dependencies": {"express": "^4.18.0"},
            "scripts": {"start": "node server.js", "dev": "nodemon server.js"},
        },
        False,
    ),
    (
        "Plugin amb peerDeps però TAMBÉ té start (app híbrida)",
        {
            "name": "storybook-addon",
            "peerDependencies": {"react": ">=17"},
            "scripts": {"start": "storybook dev", "build": "tsc"},
        },
        False,  # peerDeps(+1) + no files/exports/publishConfig → 1 < 2
    ),
    (
        "Paquet amb private i peerDeps (cas ambigu → conservador = app)",
        {
            "name": "nx-plugin",
            "private": True,
            "peerDependencies": {"nx": ">=16"},
            "scripts": {"build": "tsc"},
        },
        False,  # private(-1) + peerDeps(+1) + no script(+1) = 1 < 2
    ),
]

passed = 0
failed = 0
for desc, pkg, expected in CASES:
    result = is_node_library(pkg)
    ok = result == expected
    status = "✅" if ok else "❌"
    label = "library" if expected else "app"
    print(f"  {status} [{label:7}] {desc}")
    if not ok:
        print(f"           → esperat={expected}, obtingut={result}")
        failed += 1
    else:
        passed += 1

print(f"\n{'='*60}")
print(f"  {passed}/{passed+failed} tests passats")
if failed:
    print(f"  ❌ {failed} FALLITS")
    sys.exit(1)
else:
    print("  Tots correctes.")
