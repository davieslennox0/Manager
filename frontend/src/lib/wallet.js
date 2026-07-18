// Browser-wallet bridge for SignatureRegistry on X Layer (chain 196).
// All onchain writes come from the user's wallet — the backend only verifies.
import { BrowserProvider, Contract } from "ethers";

export const REGISTRY_ABI = [
  "function createAgreement(bytes32 docHash, address[] signers, uint8 mode, string metadata) returns (uint256)",
  "function sign(uint256 id)",
  "function getAgreement(uint256 id) view returns (bytes32,address,uint8,string,address[],uint64,uint64,uint32)",
  "event AgreementCreated(uint256 indexed id, bytes32 indexed docHash, address indexed creator, uint8 mode)",
];

const XLAYER = {
  chainId: "0xc4", // 196
  chainName: "X Layer",
  nativeCurrency: { name: "OKB", symbol: "OKB", decimals: 18 },
  rpcUrls: ["https://rpc.xlayer.tech"],
  blockExplorerUrls: ["https://www.okx.com/web3/explorer/xlayer"],
};

export function explorerTx(hash) {
  return `${XLAYER.blockExplorerUrls[0]}/tx/${hash}`;
}

export async function connectWallet(expectedChainId) {
  if (!window.ethereum) {
    throw new Error("No browser wallet found — install OKX Wallet or MetaMask.");
  }
  await window.ethereum.request({ method: "eth_requestAccounts" });
  const wanted = "0x" + Number(expectedChainId || 196).toString(16);
  const current = await window.ethereum.request({ method: "eth_chainId" });
  if (current !== wanted) {
    try {
      await window.ethereum.request({
        method: "wallet_switchEthereumChain",
        params: [{ chainId: wanted }],
      });
    } catch (err) {
      if (err.code === 4902) {
        await window.ethereum.request({ method: "wallet_addEthereumChain", params: [XLAYER] });
      } else {
        throw err;
      }
    }
  }
  const provider = new BrowserProvider(window.ethereum);
  const signer = await provider.getSigner();
  return { provider, signer, address: await signer.getAddress() };
}

export async function sendCreateAgreement(txRequest) {
  const { signer } = await connectWallet(txRequest.chain_id);
  const registry = new Contract(txRequest.registry, REGISTRY_ABI, signer);
  const [docHash, signers, mode, metadata] = txRequest.args;
  const tx = await registry.createAgreement(docHash, signers, mode, metadata);
  const receipt = await tx.wait();
  // AgreementCreated's first indexed topic is the onchain agreement id.
  const created = receipt.logs
    .map((log) => { try { return registry.interface.parseLog(log); } catch { return null; } })
    .find((parsed) => parsed && parsed.name === "AgreementCreated");
  if (!created) throw new Error("Transaction mined but AgreementCreated event not found");
  return { txHash: receipt.hash, chainAgreementId: Number(created.args.id) };
}

export async function sendSign(registryAddress, chainAgreementId) {
  const { signer } = await connectWallet(196);
  const registry = new Contract(registryAddress, REGISTRY_ABI, signer);
  const tx = await registry.sign(chainAgreementId);
  const receipt = await tx.wait();
  return { txHash: receipt.hash };
}
