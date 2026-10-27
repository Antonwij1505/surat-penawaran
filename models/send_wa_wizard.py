import urllib.parse
from odoo import api, fields, models
from odoo.exceptions import ValidationError


class SendWaWizard(models.TransientModel):
    _name = "send.wa.wizard"
    _description = "Preview & Kirim Pesan WhatsApp (Click to Chat)"

    doc_model = fields.Char(string="Model Dokumen", required=True)
    doc_id = fields.Integer(string="ID Dokumen", required=True)
    doc_name = fields.Char(string="Nomor Dokumen")

    partner_id = fields.Many2one("res.partner", string="Customer / Instansi", readonly=True)
    recipient_name = fields.Char(string="Nama Penerima (PIC)", required=True)
    recipient_phone = fields.Char(
        string="Nomor WhatsApp Tujuan",
        required=True,
        help="Format: 08123456789 atau 628123456789",
    )

    message = fields.Text(
        string="Pratinjau Pesan WhatsApp",
        required=True,
        help="Anda dapat mengedit isi pesan ini sebelum membuka WhatsApp.",
    )

    def action_download_pdf(self):
        """Aksi download file PDF dokumen terkait agar sales mudah melampirkannya di WhatsApp Web."""
        self.ensure_one()
        report_xml_id = (
            "agi_surat_penawaran.action_report_surat_penawaran"
            if self.doc_model == "surat.penawaran"
            else "agi_surat_penawaran.action_report_customer_po"
        )
        return self.env.ref(report_xml_id).report_action(self.doc_id)

    def action_confirm_send(self):
        """Buka WhatsApp Web / App secara aman via Click to Chat resmi (wa.me) tanpa bot/API luar."""
        self.ensure_one()
        phone = (self.recipient_phone or "").strip()
        clean_phone = "".join(filter(str.isdigit, phone))
        if clean_phone.startswith("0"):
            clean_phone = "62" + clean_phone[1:]
        elif clean_phone.startswith("8"):
            clean_phone = "62" + clean_phone

        if not clean_phone or len(clean_phone) < 8:
            raise ValidationError("Nomor WhatsApp tujuan tidak valid!")

        # Ambil record dokumen terkait
        doc = self.env[self.doc_model].browse(self.doc_id)
        if not doc.exists():
            raise ValidationError("Dokumen tidak ditemukan!")

        # Update status & trigger CRM
        if self.doc_model == "surat.penawaran":
            doc.write({
                "state": "sent",
                "pic_phone": phone,
            })
            if self.recipient_name and not doc.pic_name:
                doc.write({"pic_name": self.recipient_name})
            doc._trigger_crm_p2()
        elif self.doc_model == "customer.po":
            doc.write({
                "signer_mobile": phone,
            })
            if self.recipient_name and not doc.signer_name:
                doc.write({"signer_name": self.recipient_name})
            doc._trigger_crm_p1()

        # Sinkronisasi nomor WhatsApp HANYA ke field mobile (jangan sentuh field phone/telepon kantor)
        lead = getattr(doc, 'opportunity_id', False)
        if lead:
            lead_vals = {}
            if not lead.mobile or lead.mobile != phone:
                lead_vals['mobile'] = phone
            if self.recipient_name and not lead.contact_name:
                lead_vals['contact_name'] = self.recipient_name
            if lead_vals:
                lead.write(lead_vals)

        partner = getattr(doc, 'partner_id', False)
        if partner:
            partner_vals = {}
            if not partner.mobile or partner.mobile != phone:
                partner_vals['mobile'] = phone
            if partner_vals:
                partner.write(partner_vals)

        # Log chatter pada dokumen
        doc.message_post(
            body=f"💬 **Pesan WhatsApp Dibuka via Click to Chat (wa.me)** untuk nomor {clean_phone} ({self.recipient_name})."
        )

        # Generate Click to Chat URL (wa.me)
        encoded_msg = urllib.parse.quote(self.message)
        wa_url = f"https://wa.me/{clean_phone}?text={encoded_msg}"

        return {
            "type": "ir.actions.act_url",
            "url": wa_url,
            "target": "new",
        }
