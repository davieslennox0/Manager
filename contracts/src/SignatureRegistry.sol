// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @title SignatureRegistry — onchain multi-party document signing
/// @notice Stores a document hash, its signer set, and each signer's wallet
///         signature (a sign() transaction). Dual privacy: HASH_ONLY keeps
///         nothing but the hash onchain; WITH_METADATA additionally stores a
///         caller-supplied metadata string (e.g. title + parties). When every
///         signer has signed, the agreement is Executed — a timestamped,
///         unfakeable record any verifier can check against the offchain doc.
contract SignatureRegistry {
    enum PrivacyMode {
        HASH_ONLY,
        WITH_METADATA
    }

    struct Agreement {
        bytes32 docHash;
        address creator;
        PrivacyMode mode;
        string metadata; // always empty in HASH_ONLY mode
        address[] signers;
        uint64 createdAt;
        uint64 executedAt; // 0 until every signer has signed
        uint32 signedCount;
    }

    uint256 public agreementCount;
    mapping(uint256 => Agreement) private _agreements;
    /// agreement id => signer => block timestamp of their signature (0 = unsigned)
    mapping(uint256 => mapping(address => uint64)) public signedAt;

    event AgreementCreated(
        uint256 indexed id, bytes32 indexed docHash, address indexed creator, PrivacyMode mode
    );
    event Signed(uint256 indexed id, address indexed signer, uint32 signedCount);
    event Executed(uint256 indexed id, bytes32 indexed docHash, uint64 executedAt);

    function createAgreement(
        bytes32 docHash,
        address[] calldata signers,
        PrivacyMode mode,
        string calldata metadata
    ) external returns (uint256 id) {
        require(docHash != bytes32(0), "doc hash required");
        require(signers.length > 0 && signers.length <= 16, "1-16 signers");
        if (mode == PrivacyMode.HASH_ONLY) {
            require(bytes(metadata).length == 0, "no metadata in HASH_ONLY");
        }
        for (uint256 i = 0; i < signers.length; i++) {
            require(signers[i] != address(0), "zero signer");
            for (uint256 k = i + 1; k < signers.length; k++) {
                require(signers[i] != signers[k], "duplicate signer");
            }
        }
        id = ++agreementCount;
        Agreement storage a = _agreements[id];
        a.docHash = docHash;
        a.creator = msg.sender;
        a.mode = mode;
        a.metadata = metadata;
        a.signers = signers;
        a.createdAt = uint64(block.timestamp);
        emit AgreementCreated(id, docHash, msg.sender, mode);
    }

    /// @notice Sign as msg.sender — the wallet signature IS the transaction.
    function sign(uint256 id) external {
        Agreement storage a = _agreements[id];
        require(a.docHash != bytes32(0), "no such agreement");
        require(a.executedAt == 0, "already executed");
        require(signedAt[id][msg.sender] == 0, "already signed");
        bool isSigner = false;
        for (uint256 i = 0; i < a.signers.length; i++) {
            if (a.signers[i] == msg.sender) {
                isSigner = true;
                break;
            }
        }
        require(isSigner, "not a signer");
        signedAt[id][msg.sender] = uint64(block.timestamp);
        a.signedCount++;
        emit Signed(id, msg.sender, a.signedCount);
        if (a.signedCount == a.signers.length) {
            a.executedAt = uint64(block.timestamp);
            emit Executed(id, a.docHash, a.executedAt);
        }
    }

    function getAgreement(uint256 id)
        external
        view
        returns (
            bytes32 docHash,
            address creator,
            PrivacyMode mode,
            string memory metadata,
            address[] memory signers,
            uint64 createdAt,
            uint64 executedAt,
            uint32 signedCount
        )
    {
        Agreement storage a = _agreements[id];
        require(a.docHash != bytes32(0), "no such agreement");
        return (a.docHash, a.creator, a.mode, a.metadata, a.signers, a.createdAt, a.executedAt, a.signedCount);
    }

    /// @notice True once every listed signer has signed.
    function isExecuted(uint256 id) external view returns (bool) {
        return _agreements[id].executedAt != 0;
    }
}
