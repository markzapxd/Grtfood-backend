#!/usr/bin/env python3
import argparse
import json
import sys
from urllib import error, request


def http_json(url: str):
    req = request.Request(url, method="GET")
    req.add_header("Accept", "application/json")
    with request.urlopen(req, timeout=15) as resp:
        body = resp.read().decode("utf-8")
        return json.loads(body)


def http_delete(url: str):
    req = request.Request(url, method="DELETE")
    with request.urlopen(req, timeout=15) as resp:
        return resp.status


def main():
    parser = argparse.ArgumentParser(
        description="Apaga todos os pedidos da API (GET /api/pedidos + DELETE /api/pedidos/{id})."
    )
    parser.add_argument(
        "--base-url",
        default="http://10.0.0.137:8000",
        help="Base da API (padrão: http://10.0.0.137:8000)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Só lista os pedidos que seriam removidos, sem deletar.",
    )
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")
    list_url = f"{base_url}/api/pedidos"

    try:
        pedidos = http_json(list_url)
    except error.HTTPError as exc:
        print(f"Erro ao listar pedidos ({exc.code}): {exc.reason}")
        return 1
    except Exception as exc:
        print(f"Erro ao listar pedidos: {exc}")
        return 1

    if not isinstance(pedidos, list):
        print("Resposta inesperada da API em /api/pedidos (esperado array).")
        return 1

    if not pedidos:
        print("Nenhum pedido para remover.")
        return 0

    ids = [p.get("id") for p in pedidos if isinstance(p, dict) and p.get("id") is not None]
    print(f"Pedidos encontrados: {len(ids)}")

    if args.dry_run:
        print("IDs que seriam removidos:", ", ".join(str(i) for i in ids))
        return 0

    removed = 0
    failed = 0

    for pedido_id in ids:
        delete_url = f"{base_url}/api/pedidos/{pedido_id}"
        try:
            status = http_delete(delete_url)
            if status in (200, 202, 204):
                removed += 1
                print(f"OK: pedido {pedido_id} removido (HTTP {status})")
            else:
                failed += 1
                print(f"FALHA: pedido {pedido_id} retornou HTTP {status}")
        except error.HTTPError as exc:
            failed += 1
            print(f"FALHA: pedido {pedido_id} (HTTP {exc.code})")
        except Exception as exc:
            failed += 1
            print(f"FALHA: pedido {pedido_id} ({exc})")

    print("---")
    print(f"Removidos: {removed}")
    print(f"Falhas: {failed}")
    return 0 if failed == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
