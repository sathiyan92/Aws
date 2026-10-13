"""
Over-The-Air (OTA) Firmware Management API endpoints.
Provides firmware binary uploads, version cataloging, deployment targeting,
binary streaming downloads, and edge device status reporting.
"""
import os
import hashlib
from typing import List, Optional
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, File, Form, UploadFile, Request, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from src.db.session import get_db
from src.db.base import utc_now, generate_uuid
from src.db.models.device import Device, DeviceType
from src.db.models.firmware import FirmwareVersion, OTADeployment
from src.db.models.audit import AuditLog
from src.core.security.dependencies import (
    TenantContext,
    get_tenant_context,
    require_roles,
    get_authenticated_device,
)
from src.core.exceptions.errors import (
    NotFoundException,
    BadRequestException,
    ForbiddenException,
)
from src.api.v1.ota.schemas import (
    FirmwareVersionResponse,
    FirmwareListResponse,
    OTADeploymentResponse,
    OTADeploymentListResponse,
    OTAPushRequest,
    DeviceOTACheckResponse,
    DeviceOTAStatusReportRequest,
)

router = APIRouter(prefix="/ota", tags=["Over-The-Air (OTA) Firmware Updates"])

UPLOAD_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../../uploads/firmware"))
os.makedirs(UPLOAD_DIR, exist_ok=True)


def serialize_firmware(f: FirmwareVersion) -> FirmwareVersionResponse:
    return FirmwareVersionResponse(
        id=f.id,
        version_string=f.version_string,
        hardware_revision=f.hardware_revision,
        device_type_code=f.device_type.code if f.device_type else "UNKNOWN",
        file_size_bytes=f.file_size_bytes,
        sha256_checksum=f.sha256_checksum,
        binary_url=f.binary_url,
        changelog=f.changelog,
        is_deprecated=f.is_deprecated,
        created_at=f.created_at,
    )


def serialize_deployment(d: OTADeployment) -> OTADeploymentResponse:
    return OTADeploymentResponse(
        id=d.id,
        device_id=d.device_id,
        device_code=d.device.device_id if d.device else "UNKNOWN",
        firmware_version_id=d.firmware_version_id,
        version_string=d.firmware_version.version_string if d.firmware_version else "UNKNOWN",
        deployment_status=d.deployment_status,
        error_message=d.error_message,
        started_at=d.started_at,
        completed_at=d.completed_at,
        created_at=d.created_at,
    )


# ==============================================================================
# 1. MANUFACTURER OPERATIONS: FIRMWARE UPLOAD & DEPLOYMENT MANAGEMENT
# ==============================================================================

@router.post("/firmware/upload", response_model=FirmwareVersionResponse)
async def upload_firmware_binary(
    request: Request,
    file: UploadFile = File(...),
    version_string: str = Form(...),
    device_type_code: str = Form("VENDING_MACHINE"),
    hardware_revision: str = Form("HW-ESP32S3-V1.2"),
    changelog: Optional[str] = Form(None),
    target_device_id: Optional[str] = Form(None),
    context: TenantContext = Depends(require_roles("MANUFACTURER_ADMIN")),
    db: Session = Depends(get_db),
):
    """
    [Manufacturer Only] Upload a compiled ESP32 firmware binary (.bin).
    Computes cryptographic SHA-256 hash, stores file artifact, and registers in catalog.
    If target_device_id is provided, automatically triggers deployment for that machine.
    """
    if not file.filename.endswith((".bin", ".elf")):
        raise BadRequestException("Invalid firmware artifact: File must be an ESP32 compiled binary (.bin)")

    dev_type = db.query(DeviceType).filter_by(code=device_type_code).first()
    if not dev_type:
        raise NotFoundException("DeviceType", device_type_code)

    # Clean version string (e.g. v1.1.0)
    v_clean = version_string.strip()
    if not v_clean.startswith("v"):
        v_clean = f"v{v_clean}"

    # Generate unique filename on disk
    file_uuid = generate_uuid()[:8]
    sanitized_name = f"{device_type_code.lower()}_{v_clean.replace('.', '_')}_{file_uuid}.bin"
    file_path = os.path.join(UPLOAD_DIR, sanitized_name)

    # Stream file to disk and calculate SHA-256
    sha256_hasher = hashlib.sha256()
    file_size = 0

    with open(file_path, "wb") as out_f:
        while chunk := await file.read(65536):
            sha256_hasher.update(chunk)
            out_f.write(chunk)
            file_size += len(chunk)

    checksum = sha256_hasher.hexdigest()

    # Construct public binary download URL
    base_url = str(request.base_url).rstrip("/")
    download_url = f"{base_url}/api/v1/ota/binaries/{sanitized_name}"

    # Create FirmwareVersion record
    fw_version = FirmwareVersion(
        device_type_id=dev_type.id,
        version_string=v_clean,
        hardware_revision=hardware_revision.strip(),
        binary_url=download_url,
        file_size_bytes=file_size,
        sha256_checksum=checksum,
        signature=f"sig_{checksum[:32]}",  # Internal digital verification signature
        changelog=changelog.strip() if changelog else None,
        created_by_user_id=context.user.id,
    )
    db.add(fw_version)
    db.flush()

    # Audit log
    db.add(AuditLog(
        client_id=None,
        user_id=context.user.id,
        action="FIRMWARE_UPLOADED",
        entity_type="FIRMWARE",
        entity_id=fw_version.id,
        new_state={
            "version": v_clean,
            "device_type": device_type_code,
            "size_bytes": file_size,
            "sha256": checksum,
            "filename": sanitized_name,
        },
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    ))

    # If target device specified, trigger deployment immediately
    if target_device_id and target_device_id.strip():
        target_dev = db.query(Device).filter(
            (Device.device_id == target_device_id.strip()) | (Device.id == target_device_id.strip())
        ).first()
        if target_dev:
            # Supersede existing pending deployments
            pending = db.query(OTADeployment).filter(
                OTADeployment.device_id == target_dev.id,
                OTADeployment.deployment_status == "PENDING"
            ).all()
            for p in pending:
                p.deployment_status = "SUPERSEDED"

            deployment = OTADeployment(
                firmware_version_id=fw_version.id,
                device_id=target_dev.id,
                client_id=target_dev.client_id,
                deployment_status="PENDING",
                created_by_user_id=context.user.id,
            )
            db.add(deployment)
            db.add(AuditLog(
                client_id=target_dev.client_id,
                user_id=context.user.id,
                action="OTA_TRIGGER",
                entity_type="DEVICE",
                entity_id=target_dev.device_id,
                new_state={"firmware_version": v_clean, "deployment_id": deployment.id},
                ip_address=request.client.host if request.client else None,
                user_agent=request.headers.get("user-agent"),
            ))

    db.commit()
    db.refresh(fw_version)
    return serialize_firmware(fw_version)


@router.get("/firmware", response_model=FirmwareListResponse)
def list_firmware_versions(
    device_type: Optional[str] = Query(None, description="Filter by device type code"),
    context: TenantContext = Depends(require_roles("MANUFACTURER_ADMIN")),
    db: Session = Depends(get_db),
):
    """[Manufacturer Only] List all uploaded firmware binaries."""
    query = db.query(FirmwareVersion)
    if device_type:
        query = query.join(DeviceType).filter(DeviceType.code == device_type)
    firmwares = query.order_by(FirmwareVersion.created_at.desc()).all()
    return FirmwareListResponse(
        total=len(firmwares),
        firmware_versions=[serialize_firmware(f) for f in firmwares],
    )


@router.post("/deploy", response_model=OTADeploymentResponse)
def trigger_ota_deployment(
    payload: OTAPushRequest,
    request: Request,
    context: TenantContext = Depends(require_roles("MANUFACTURER_ADMIN")),
    db: Session = Depends(get_db),
):
    """
    [Manufacturer Only] Push a firmware update to a particular physical ESP32 device.
    """
    device = db.query(Device).filter(
        (Device.device_id == payload.device_id) | (Device.id == payload.device_id)
    ).first()
    if not device:
        raise NotFoundException("Device", payload.device_id)

    firmware = db.query(FirmwareVersion).filter_by(id=payload.firmware_version_id).first()
    if not firmware:
        raise NotFoundException("FirmwareVersion", payload.firmware_version_id)

    # Supersede existing pending deployments
    pending = db.query(OTADeployment).filter(
        OTADeployment.device_id == device.id,
        OTADeployment.deployment_status == "PENDING"
    ).all()
    for p in pending:
        p.deployment_status = "SUPERSEDED"

    deployment = OTADeployment(
        firmware_version_id=firmware.id,
        device_id=device.id,
        client_id=device.client_id,
        deployment_status="PENDING",
        created_by_user_id=context.user.id,
    )
    db.add(deployment)

    db.add(AuditLog(
        client_id=device.client_id,
        user_id=context.user.id,
        action="OTA_TRIGGER",
        entity_type="DEVICE",
        entity_id=device.device_id,
        new_state={"firmware_version": firmware.version_string, "deployment_id": deployment.id},
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    ))

    db.commit()
    db.refresh(deployment)
    return serialize_deployment(deployment)


@router.get("/deployments", response_model=OTADeploymentListResponse)
def list_ota_deployments(
    device_id: Optional[str] = Query(None, description="Filter deployments by device identifier"),
    context: TenantContext = Depends(get_tenant_context),
    db: Session = Depends(get_db),
):
    """List OTA deployment history."""
    query = db.query(OTADeployment)
    if device_id:
        target = db.query(Device).filter((Device.device_id == device_id) | (Device.id == device_id)).first()
        if target:
            context.assert_device_access(target)
            query = query.filter(OTADeployment.device_id == target.id)
    elif not context.is_manufacturer:
        query = query.filter(OTADeployment.client_id == context.client_id)

    deployments = query.order_by(OTADeployment.created_at.desc()).limit(50).all()
    return OTADeploymentListResponse(
        total=len(deployments),
        deployments=[serialize_deployment(d) for d in deployments],
    )


@router.get("/binaries/{filename}")
def download_firmware_binary(filename: str):
    """
    Public firmware binary streaming endpoint.
    Used by ESP32 HTTPClient / HTTPUpdate to download the binary during OTA.
    """
    # Prevent path traversal attacks
    safe_filename = os.path.basename(filename)
    file_path = os.path.join(UPLOAD_DIR, safe_filename)
    if not os.path.exists(file_path):
        raise NotFoundException("FirmwareBinary", filename)

    return FileResponse(
        file_path,
        media_type="application/octet-stream",
        filename=safe_filename,
    )


# ==============================================================================
# 2. EDGE DEVICE ENDPOINTS: CHECK FOR OTA & REPORT STATUS
# ==============================================================================

@router.get("/check/{device_id}", response_model=DeviceOTACheckResponse)
def check_for_pending_ota(
    device_id: str,
    db: Session = Depends(get_db),
):
    """
    [Edge Gateway] Polled by ESP32 hardware to check if an OTA firmware update is waiting.
    """
    device = db.query(Device).filter(
        (Device.device_id == device_id) | (Device.id == device_id)
    ).first()
    if not device:
        return DeviceOTACheckResponse(has_update=False)

    deployment = db.query(OTADeployment).filter(
        OTADeployment.device_id == device.id,
        OTADeployment.deployment_status == "PENDING"
    ).order_by(OTADeployment.created_at.desc()).first()

    if not deployment or not deployment.firmware_version:
        return DeviceOTACheckResponse(has_update=False)

    fw = deployment.firmware_version
    return DeviceOTACheckResponse(
        has_update=True,
        deployment_id=deployment.id,
        version=fw.version_string,
        binary_url=fw.binary_url,
        sha256=fw.sha256_checksum,
        file_size_bytes=fw.file_size_bytes,
    )


@router.post("/status")
def report_device_ota_status(
    payload: DeviceOTAStatusReportRequest,
    db: Session = Depends(get_db),
):
    """
    [Edge Gateway] Called by ESP32 during and after flashing to report result.
    If status is SUCCESS, automatically updates the device's current_firmware_version!
    """
    deployment = db.query(OTADeployment).filter_by(id=payload.deployment_id).first()
    if not deployment:
        raise NotFoundException("OTADeployment", payload.deployment_id)

    status_clean = payload.status.strip().upper()
    deployment.deployment_status = status_clean

    if status_clean == "DOWNLOADING":
        if not deployment.started_at:
            deployment.started_at = utc_now()
    elif status_clean == "SUCCESS":
        deployment.completed_at = utc_now()
        deployment.error_message = None
        # Bump running firmware on device entity
        if deployment.device and deployment.firmware_version:
            deployment.device.current_firmware_version = deployment.firmware_version.version_string
    elif status_clean == "FAILED":
        deployment.completed_at = utc_now()
        deployment.error_message = payload.error_message or "Unknown OTA failure"

    db.commit()
    return {
        "status": "acknowledged",
        "deployment_id": deployment.id,
        "deployment_status": status_clean,
    }
