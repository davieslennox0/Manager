"""Read-side bridge to SignatureRegistry on X Layer. All writes (createAgreement,
sign) happen from the user's browser wallet; the backend only verifies onchain
state before flipping local status — no server-side keys, no mocked reads."""
from web3 import Web3

import config

REGISTRY_ABI = [
    {"type": "function", "name": "agreementCount", "inputs": [],
     "outputs": [{"type": "uint256"}], "stateMutability": "view"},
    {"type": "function", "name": "getAgreement",
     "inputs": [{"name": "id", "type": "uint256"}],
     "outputs": [{"name": "docHash", "type": "bytes32"},
                 {"name": "creator", "type": "address"},
                 {"name": "mode", "type": "uint8"},
                 {"name": "metadata", "type": "string"},
                 {"name": "signers", "type": "address[]"},
                 {"name": "createdAt", "type": "uint64"},
                 {"name": "executedAt", "type": "uint64"},
                 {"name": "signedCount", "type": "uint32"}],
     "stateMutability": "view"},
    {"type": "function", "name": "signedAt",
     "inputs": [{"type": "uint256"}, {"type": "address"}],
     "outputs": [{"type": "uint64"}], "stateMutability": "view"},
    {"type": "function", "name": "createAgreement",
     "inputs": [{"name": "docHash", "type": "bytes32"},
                {"name": "signers", "type": "address[]"},
                {"name": "mode", "type": "uint8"},
                {"name": "metadata", "type": "string"}],
     "outputs": [{"type": "uint256"}], "stateMutability": "nonpayable"},
    {"type": "function", "name": "sign",
     "inputs": [{"name": "id", "type": "uint256"}],
     "outputs": [], "stateMutability": "nonpayable"},
]


def _w3() -> Web3:
    return Web3(Web3.HTTPProvider(config.XLAYER_RPC_URL, request_kwargs={"timeout": 20}))


def registry():
    if not config.REGISTRY_ADDRESS:
        raise RuntimeError("SIGNATURE_REGISTRY_ADDRESS not configured")
    w3 = _w3()
    return w3.eth.contract(address=Web3.to_checksum_address(config.REGISTRY_ADDRESS),
                           abi=REGISTRY_ABI)


def read_agreement(chain_id: int) -> dict:
    """Onchain truth for one agreement, normalized for the API."""
    c = registry()
    (doc_hash, creator, mode, metadata, signers,
     created_at, executed_at, signed_count) = c.functions.getAgreement(chain_id).call()
    signed = {s.lower(): c.functions.signedAt(chain_id, s).call() for s in signers}
    return {
        "chain_agreement_id": chain_id,
        "doc_hash": "0x" + doc_hash.hex(),
        "creator": creator.lower(),
        "privacy_mode": "WITH_METADATA" if mode == 1 else "HASH_ONLY",
        "metadata": metadata,
        "signers": [s.lower() for s in signers],
        "signed_at": signed,
        "created_at": created_at,
        "executed_at": executed_at,
        "executed": executed_at != 0,
        "signed_count": signed_count,
    }


def tx_receipt_status(tx_hash: str) -> int | None:
    """1 success, 0 revert, None if not yet mined/unknown."""
    try:
        receipt = _w3().eth.get_transaction_receipt(tx_hash)
        return receipt["status"]
    except Exception:
        return None
