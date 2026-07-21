"""Self-hosted seller side of the OKX Agent Payments Protocol (x402 v2, exact scheme).

No external facilitator: this process verifies the buyer's signature and broadcasts the
settlement itself, using its own funded relayer key for gas. Accepts both transfer
methods the SDK's exact scheme supports -- EIP-3009 transferWithAuthorization (no buyer
pre-approval; X Layer's USDT0 implements it natively) and Permit2 (any ERC-20, needs the
buyer's one-time on-chain approve to the Permit2 contract).

This is Pitchook's own copy of the pattern Manny, Bondsman, and Engram use -- kept
self-contained here rather than imported cross-repo, matching how every ASP under
this account carries its own x402 seller.
"""
from __future__ import annotations

from web3 import Web3
from eth_account import Account
from eth_account.messages import encode_typed_data

from x402.schemas import (
    PaymentPayload,
    PaymentRequirements,
    SettleResponse,
    SupportedKind,
    SupportedResponse,
    VerifyResponse,
)
from x402.mechanisms.evm.exact.facilitator import ExactEvmScheme as ExactEvmFacilitatorScheme
from x402.mechanisms.evm.types import TransactionReceipt

NETWORK = "eip155:196"  # X Layer mainnet


def _hex(b) -> str:
    h = b.hex()
    return h if h.startswith("0x") else "0x" + h


def _checksum_args(args):
    """web3.py rejects non-checksummed address strings in ABI args; the SDK passes
    addresses through verbatim (e.g. a lowercase payTo), so normalize them here."""
    return tuple(
        Web3.to_checksum_address(a)
        if isinstance(a, str) and len(a) == 42 and a.startswith("0x")
        else a
        for a in args
    )


class EvmFacilitatorSigner:
    """Implements x402's FacilitatorEvmSigner protocol on top of web3.py."""

    def __init__(self, rpc_url: str, private_key: str):
        self.w3 = Web3(Web3.HTTPProvider(rpc_url))
        self.account = Account.from_key(private_key)

    def get_addresses(self) -> list[str]:
        return [self.account.address]

    def get_chain_id(self) -> int:
        return self.w3.eth.chain_id

    def get_code(self, address: str) -> bytes:
        return self.w3.eth.get_code(Web3.to_checksum_address(address))

    def read_contract(self, address, abi, function_name, *args):
        contract = self.w3.eth.contract(address=Web3.to_checksum_address(address), abi=abi)
        return getattr(contract.functions, function_name)(*_checksum_args(args)).call()

    def write_contract(self, address, abi, function_name, *args,
                       data_suffix: str | None = None) -> str:
        # data_suffix: SDK >= 2.15 passes it on every settle (ERC-8021 builder-code
        # attribution); it's an optional hex tail appended to the encoded calldata.
        contract = self.w3.eth.contract(address=Web3.to_checksum_address(address), abi=abi)
        fn = getattr(contract.functions, function_name)(*_checksum_args(args))
        tx = fn.build_transaction(
            {
                "from": self.account.address,
                "nonce": self.w3.eth.get_transaction_count(self.account.address),
                "chainId": self.w3.eth.chain_id,
            }
        )
        if data_suffix:
            data = tx["data"]
            if isinstance(data, (bytes, bytearray)):
                data = "0x" + bytes(data).hex()
            tx["data"] = data + data_suffix.removeprefix("0x")
            tx.pop("gas", None)
            tx["gas"] = self.w3.eth.estimate_gas(tx)  # re-estimate with the suffixed calldata
        signed = self.account.sign_transaction(tx)
        tx_hash = self.w3.eth.send_raw_transaction(signed.raw_transaction)
        return _hex(tx_hash)

    def send_transaction(self, to: str, data: bytes) -> str:
        tx = {
            "from": self.account.address,
            "to": Web3.to_checksum_address(to),
            "data": data,
            "nonce": self.w3.eth.get_transaction_count(self.account.address),
            "chainId": self.w3.eth.chain_id,
        }
        tx["gas"] = self.w3.eth.estimate_gas(tx)
        tx["gasPrice"] = self.w3.eth.gas_price
        signed = self.account.sign_transaction(tx)
        tx_hash = self.w3.eth.send_raw_transaction(signed.raw_transaction)
        return _hex(tx_hash)

    def wait_for_transaction_receipt(self, tx_hash: str) -> TransactionReceipt:
        r = self.w3.eth.wait_for_transaction_receipt(tx_hash)
        return TransactionReceipt(status=r.status, block_number=r.blockNumber, tx_hash=_hex(r.transactionHash))

    def get_balance(self, address: str, token_address: str) -> int:
        abi = [
            {
                "constant": True,
                "inputs": [{"name": "_owner", "type": "address"}],
                "name": "balanceOf",
                "outputs": [{"name": "balance", "type": "uint256"}],
                "type": "function",
            }
        ]
        return self.read_contract(token_address, abi, "balanceOf", Web3.to_checksum_address(address))

    def verify_typed_data(self, address, domain, types, primary_type, message, signature) -> bool:
        type_map = {
            "name": "string",
            "version": "string",
            "chainId": "uint256",
            "verifyingContract": "address",
            "salt": "bytes32",
        }
        domain_fields = [
            {"name": k, "type": type_map[k]} for k in type_map if domain.get(k) is not None
        ]
        full_types = {"EIP712Domain": domain_fields}
        for type_name, fields in types.items():
            full_types[type_name] = [{"name": f.name, "type": f.type} for f in fields]
        full_message = {
            "types": full_types,
            "domain": domain,
            "primaryType": primary_type,
            "message": message,
        }
        try:
            signable = encode_typed_data(full_message=full_message)
            recovered = Account.recover_message(signable, signature=signature)
            return recovered.lower() == address.lower()
        except Exception:
            return False


class LocalFacilitatorClient:
    """Facilitator client backed by our own signer -- conforms to the x402 SDK's
    FacilitatorClient protocol so PaymentMiddlewareASGI can drive verify/settle
    without an external facilitator service. Delegates to the SDK's exact-scheme
    facilitator, which routes each payload to Permit2 or EIP-3009 by its shape.
    """

    def __init__(self, signer: EvmFacilitatorSigner, network: str = NETWORK):
        self._signer = signer
        self._network = network
        self._scheme = ExactEvmFacilitatorScheme(signer)

    async def verify(self, payload: PaymentPayload, requirements: PaymentRequirements) -> VerifyResponse:
        return self._scheme.verify(payload, requirements)

    async def settle(self, payload: PaymentPayload, requirements: PaymentRequirements) -> SettleResponse:
        return self._scheme.settle(payload, requirements)

    def get_supported(self) -> SupportedResponse:
        return SupportedResponse(
            kinds=[SupportedKind(x402_version=2, scheme="exact", network=self._network)],
            signers={"eip155": [self._signer.account.address]},
        )
