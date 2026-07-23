import calendar
import uuid
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator, MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone


ALLOWED_UPLOAD_EXTENSIONS = ['jpg', 'jpeg', 'png', 'webp', 'pdf']
IMAGE_UPLOAD_EXTENSIONS = ['jpg', 'jpeg', 'png', 'webp']
MAX_UPLOAD_BYTES = 5 * 1024 * 1024


def validate_upload_size(upload):
    if upload.size > MAX_UPLOAD_BYTES:
        raise ValidationError('單一檔案不可超過 5 MB。')


def rental_upload_to(instance, filename):
    prefixes = {
        'UnitPhoto': 'unit-photos',
        'LeaseDocument': 'lease-documents',
        'BillMeterReading': 'meter-readings',
        'BillPayment': 'payment-receipts',
        'MaintenanceAttachment': 'maintenance',
    }
    extension = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    prefix = prefixes.get(instance.__class__.__name__, 'uploads')
    return f'rental/{prefix}/{timezone.now():%Y/%m}/{uuid.uuid4().hex}.{extension}'


upload_validator = FileExtensionValidator(ALLOWED_UPLOAD_EXTENSIONS)
image_upload_validator = FileExtensionValidator(IMAGE_UPLOAD_EXTENSIONS)


class Property(models.Model):
    class Status(models.TextChoices):
        ACTIVE = 'active', '使用中'
        INACTIVE = 'inactive', '停用'

    name = models.CharField('物件名稱', max_length=120)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name='房東', on_delete=models.PROTECT,
        related_name='rental_properties',
    )
    address = models.CharField('地址', max_length=255)
    description = models.TextField('說明', blank=True)
    status = models.CharField('狀態', max_length=16, choices=Status.choices, default=Status.ACTIVE)
    created_at = models.DateTimeField('建立時間', auto_now_add=True)
    updated_at = models.DateTimeField('更新時間', auto_now=True)

    class Meta:
        verbose_name = '物件'
        verbose_name_plural = '物件'
        ordering = ['name']

    def __str__(self):
        return self.name


class PropertyMembership(models.Model):
    class Role(models.TextChoices):
        MANAGER = 'manager', '物件管理者'

    property = models.ForeignKey(Property, verbose_name='物件', on_delete=models.CASCADE, related_name='memberships')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name='會員', on_delete=models.CASCADE)
    role = models.CharField('角色', max_length=16, choices=Role.choices, default=Role.MANAGER)
    created_at = models.DateTimeField('建立時間', auto_now_add=True)

    class Meta:
        verbose_name = '物件管理權限'
        verbose_name_plural = '物件管理權限'
        constraints = [models.UniqueConstraint(fields=['property', 'user'], name='unique_property_membership')]

    def __str__(self):
        return f'{self.property} / {self.user}'


class Unit(models.Model):
    class Status(models.TextChoices):
        AVAILABLE = 'available', '可出租'
        OCCUPIED = 'occupied', '已出租'
        MAINTENANCE = 'maintenance', '維修中'
        INACTIVE = 'inactive', '停用'

    property = models.ForeignKey(Property, verbose_name='物件', on_delete=models.CASCADE, related_name='units')
    floor = models.CharField('樓層', max_length=30, blank=True)
    number = models.CharField('房號', max_length=40)
    room_type = models.CharField('房型', max_length=80, blank=True)
    area_ping = models.DecimalField('坪數', max_digits=7, decimal_places=2, null=True, blank=True)
    status = models.CharField('出租狀態', max_length=16, choices=Status.choices, default=Status.AVAILABLE)
    notes = models.TextField('現況說明', blank=True)

    class Meta:
        verbose_name = '房間'
        verbose_name_plural = '房間'
        ordering = ['property__name', 'floor', 'number']
        constraints = [models.UniqueConstraint(fields=['property', 'number'], name='unique_unit_number_per_property')]

    def __str__(self):
        return f'{self.property} {self.number}'


class UnitAmenity(models.Model):
    unit = models.ForeignKey(Unit, verbose_name='房間', on_delete=models.CASCADE, related_name='amenities')
    name = models.CharField('附屬設備', max_length=80)

    class Meta:
        verbose_name = '房間設備'
        verbose_name_plural = '房間設備'
        constraints = [models.UniqueConstraint(fields=['unit', 'name'], name='unique_unit_amenity')]

    def __str__(self):
        return f'{self.unit} / {self.name}'


class UnitPhoto(models.Model):
    unit = models.ForeignKey(Unit, verbose_name='房間', on_delete=models.CASCADE, related_name='photos')
    image = models.FileField('現況照片', upload_to=rental_upload_to, validators=[image_upload_validator, validate_upload_size])
    caption = models.CharField('說明', max_length=120, blank=True)
    sort_order = models.PositiveSmallIntegerField('排序', default=0)
    created_at = models.DateTimeField('上傳時間', auto_now_add=True)

    class Meta:
        verbose_name = '房間現況照片'
        verbose_name_plural = '房間現況照片'
        ordering = ['sort_order', 'created_at']

    def clean(self):
        if not self.pk and self.unit_id and UnitPhoto.objects.filter(unit_id=self.unit_id).count() >= 6:
            raise ValidationError('每間房間最多上傳 6 張現況照片。')


class TenantProfile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, verbose_name='會員', on_delete=models.CASCADE, related_name='tenant_profile')
    phone = models.CharField('聯絡電話', max_length=32, blank=True)
    emergency_contact_name = models.CharField('緊急聯絡人', max_length=80, blank=True)
    emergency_contact_phone = models.CharField('緊急聯絡電話', max_length=32, blank=True)
    notes = models.TextField('備註', blank=True)
    created_at = models.DateTimeField('建立時間', auto_now_add=True)
    updated_at = models.DateTimeField('更新時間', auto_now=True)

    class Meta:
        verbose_name = '租客資料'
        verbose_name_plural = '租客資料'

    def __str__(self):
        return self.user.get_full_name() or self.user.get_username()


class Lease(models.Model):
    class Status(models.TextChoices):
        DRAFT = 'draft', '草稿'
        ACTIVE = 'active', '有效'
        ENDED = 'ended', '已結束'
        TERMINATED = 'terminated', '提前終止'

    unit = models.ForeignKey(Unit, verbose_name='房間', on_delete=models.PROTECT, related_name='leases')
    start_date = models.DateField('起租日')
    end_date = models.DateField('到期日')
    monthly_rent = models.DecimalField('每月租金', max_digits=12, decimal_places=2, validators=[MinValueValidator(0)])
    deposit = models.DecimalField('押金', max_digits=12, decimal_places=2, validators=[MinValueValidator(0)], default=Decimal('0'))
    due_day = models.PositiveSmallIntegerField('每月應繳日', validators=[MinValueValidator(1), MaxValueValidator(28)], default=1)
    status = models.CharField('租約狀態', max_length=16, choices=Status.choices, default=Status.DRAFT)
    created_at = models.DateTimeField('建立時間', auto_now_add=True)
    updated_at = models.DateTimeField('更新時間', auto_now=True)

    class Meta:
        verbose_name = '租約'
        verbose_name_plural = '租約'
        ordering = ['-start_date']

    def __str__(self):
        return f'{self.unit} ({self.start_date}～{self.end_date})'

    def clean(self):
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValidationError('租約到期日不可早於起租日。')
        if self.unit_id and self.start_date and self.end_date:
            overlap = Lease.objects.filter(
                unit_id=self.unit_id,
                start_date__lte=self.end_date,
                end_date__gte=self.start_date,
            ).exclude(pk=self.pk).exclude(status__in=[self.Status.ENDED, self.Status.TERMINATED])
            if overlap.exists():
                raise ValidationError('此房間已有期間重疊的有效或草稿租約，請調整租約日期。')

    def due_date_for(self, period):
        last_day = calendar.monthrange(period.year, period.month)[1]
        return period.replace(day=min(self.due_day, last_day)) + timedelta(days=3)


class LeaseTenant(models.Model):
    class Status(models.TextChoices):
        INVITED = 'invited', '待接受邀請'
        ACTIVE = 'active', '入住中'
        MOVED_OUT = 'moved_out', '已退租'

    lease = models.ForeignKey(Lease, verbose_name='租約', on_delete=models.CASCADE, related_name='lease_tenants')
    tenant = models.ForeignKey(TenantProfile, verbose_name='租客', on_delete=models.PROTECT, related_name='lease_tenants')
    status = models.CharField('入住狀態', max_length=16, choices=Status.choices, default=Status.INVITED)
    move_in_date = models.DateField('入住日', null=True, blank=True)
    move_out_date = models.DateField('退租日', null=True, blank=True)
    billing_access_start_date = models.DateField('帳務權限生效日', null=True, blank=True)
    created_at = models.DateTimeField('建立時間', auto_now_add=True)

    class Meta:
        verbose_name = '租約租客'
        verbose_name_plural = '租約租客'
        constraints = [models.UniqueConstraint(fields=['lease', 'tenant'], name='unique_lease_tenant')]


class TenantInvitation(models.Model):
    lease = models.ForeignKey(Lease, verbose_name='租約', on_delete=models.CASCADE, related_name='invitations')
    invited_name = models.CharField('受邀租客姓名', max_length=80)
    invited_email = models.EmailField('受邀租客 Email', blank=True)
    billing_access_start_date = models.DateField('帳務權限生效日', null=True, blank=True)
    token = models.UUIDField('邀請識別碼', default=uuid.uuid4, unique=True, editable=False)
    expires_at = models.DateTimeField('到期時間')
    accepted_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name='接受會員', null=True, blank=True, on_delete=models.SET_NULL)
    accepted_at = models.DateTimeField('接受時間', null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name='建立者', on_delete=models.PROTECT, related_name='created_tenant_invitations')
    created_at = models.DateTimeField('建立時間', auto_now_add=True)

    class Meta:
        verbose_name = '租客邀請'
        verbose_name_plural = '租客邀請'
        ordering = ['-created_at']

    @property
    def is_usable(self):
        return self.accepted_at is None and self.expires_at > timezone.now()


class LeaseCharge(models.Model):
    class ChargeType(models.TextChoices):
        WATER = 'water', '水費'
        GAS = 'gas', '瓦斯費'
        MANAGEMENT = 'management', '管理費'
        OTHER = 'other', '其他'

    lease = models.ForeignKey(Lease, verbose_name='租約', on_delete=models.CASCADE, related_name='recurring_charges')
    name = models.CharField('項目名稱', max_length=100)
    charge_type = models.CharField('類型', max_length=16, choices=ChargeType.choices, default=ChargeType.OTHER)
    default_amount = models.DecimalField('預設金額', max_digits=12, decimal_places=2, validators=[MinValueValidator(0)])
    tenant_editable = models.BooleanField('租客可編輯', default=True)
    enabled = models.BooleanField('啟用', default=True)

    class Meta:
        verbose_name = '租約固定費用'
        verbose_name_plural = '租約固定費用'


class ElectricityRate(models.Model):
    lease = models.ForeignKey(Lease, verbose_name='租約', on_delete=models.CASCADE, related_name='electricity_rates')
    name = models.CharField('費率名稱', max_length=80, blank=True)
    start_month = models.PositiveSmallIntegerField('起始月份', validators=[MinValueValidator(1), MaxValueValidator(12)])
    end_month = models.PositiveSmallIntegerField('結束月份', validators=[MinValueValidator(1), MaxValueValidator(12)])
    rate_per_kwh = models.DecimalField('每度電價', max_digits=8, decimal_places=2, validators=[MinValueValidator(0)])

    class Meta:
        verbose_name = '季節電價'
        verbose_name_plural = '季節電價'

    def applies_to(self, month):
        return self.start_month <= month <= self.end_month if self.start_month <= self.end_month else month >= self.start_month or month <= self.end_month


class LeaseDocument(models.Model):
    lease = models.ForeignKey(Lease, verbose_name='租約', on_delete=models.CASCADE, related_name='documents')
    name = models.CharField('文件名稱', max_length=120)
    file = models.FileField('附件', upload_to=rental_upload_to, validators=[upload_validator, validate_upload_size])
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name='上傳者', null=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField('上傳時間', auto_now_add=True)

    class Meta:
        verbose_name = '租約附件'
        verbose_name_plural = '租約附件'


class Bill(models.Model):
    class Status(models.TextChoices):
        DRAFT = 'draft', '待租客填寫'
        SUBMITTED = 'submitted', '待管理者確認'
        RETURNED = 'returned', '退回待租客填寫'
        CONFIRMED = 'confirmed', '待租客付款'
        PAYMENT_SUBMITTED = 'payment_submitted', '待確認收款'
        PAID = 'paid', '已結案'
        VOID = 'void', '已作廢'

    lease = models.ForeignKey(Lease, verbose_name='租約', on_delete=models.PROTECT, related_name='bills')
    period = models.DateField('帳單月份')
    revision = models.PositiveSmallIntegerField('帳單版次', default=1)
    due_date = models.DateField('付款期限')
    status = models.CharField('帳單狀態', max_length=24, choices=Status.choices, default=Status.DRAFT)
    tenant_fill_enabled = models.BooleanField('允許租約租客補填', default=False)
    reissued_from = models.ForeignKey(
        'self', verbose_name='重新建立來源帳單', null=True, blank=True,
        on_delete=models.PROTECT, related_name='replacement_bills',
    )
    created_at = models.DateTimeField('建立時間', auto_now_add=True)
    updated_at = models.DateTimeField('更新時間', auto_now=True)
    submitted_at = models.DateTimeField('提交時間', null=True, blank=True)
    confirmed_at = models.DateTimeField('帳單確認時間', null=True, blank=True)
    paid_at = models.DateTimeField('結案時間', null=True, blank=True)

    class Meta:
        verbose_name = '帳單'
        verbose_name_plural = '帳單'
        ordering = ['-period', '-revision', '-created_at']
        constraints = [
            models.UniqueConstraint(fields=['lease', 'period', 'revision'], name='unique_bill_revision_per_lease_period'),
            models.UniqueConstraint(
                fields=['lease', 'period'], condition=~models.Q(status='void'),
                name='unique_non_void_bill_per_lease_period',
            ),
        ]

    @property
    def total_amount(self):
        return sum((line.amount for line in self.items.all()), Decimal('0'))

    @property
    def is_overdue(self):
        return self.status not in {self.Status.PAID, self.Status.VOID} and timezone.localdate() > self.due_date

    def __str__(self):
        return f'{self.lease} / {self.period:%Y-%m} #{self.revision}'

    def bills_before_current_reading(self):
        reading = BillMeterReading.objects.filter(
            bill__lease=self.lease,
            bill__period__lt=self.period,
            current_reading__isnull=False,
        ).order_by('-bill__period').first()
        return reading.current_reading if reading else None


class BillTenantPermission(models.Model):
    """An explicit, auditable exception for a tenant to work on an older bill."""

    bill = models.ForeignKey(Bill, verbose_name='帳單', on_delete=models.CASCADE, related_name='tenant_permissions')
    tenant = models.ForeignKey(LeaseTenant, verbose_name='租客租約關係', on_delete=models.CASCADE, related_name='bill_permissions')
    expires_on = models.DateField('授權到期日', null=True, blank=True)
    granted_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name='授權管理者', null=True, on_delete=models.SET_NULL, related_name='granted_bill_tenant_permissions')
    created_at = models.DateTimeField('授權時間', auto_now_add=True)

    class Meta:
        verbose_name = '帳單租客補填授權'
        verbose_name_plural = '帳單租客補填授權'
        constraints = [models.UniqueConstraint(fields=['bill', 'tenant'], name='unique_bill_tenant_permission')]

    def clean(self):
        if self.bill_id and self.tenant_id and self.bill.lease_id != self.tenant.lease_id:
            raise ValidationError('帳單與租客必須屬於同一份租約。')

    @property
    def is_active(self):
        return self.expires_on is None or self.expires_on >= timezone.localdate()


class BillLineItem(models.Model):
    class ItemType(models.TextChoices):
        RENT = 'rent', '租金'
        ELECTRICITY = 'electricity', '電費'
        WATER = 'water', '水費'
        GAS = 'gas', '瓦斯費'
        MANAGEMENT = 'management', '管理費'
        OTHER = 'other', '其他'

    bill = models.ForeignKey(Bill, verbose_name='帳單', on_delete=models.CASCADE, related_name='items')
    item_type = models.CharField('項目類型', max_length=16, choices=ItemType.choices, default=ItemType.OTHER)
    name = models.CharField('項目名稱', max_length=100)
    amount = models.DecimalField('金額', max_digits=12, decimal_places=2, validators=[MinValueValidator(0)])
    tenant_editable = models.BooleanField('租客可編輯', default=False)
    sort_order = models.PositiveSmallIntegerField('排序', default=0)

    class Meta:
        verbose_name = '帳單項目'
        verbose_name_plural = '帳單項目'
        ordering = ['sort_order', 'id']


class BillMeterReading(models.Model):
    bill = models.OneToOneField(Bill, verbose_name='帳單', on_delete=models.CASCADE, related_name='meter_reading')
    reading_date = models.DateField('抄表日期', default=timezone.localdate)
    previous_reading = models.DecimalField('前次度數', max_digits=10, decimal_places=2, null=True, blank=True)
    current_reading = models.DecimalField('本次度數', max_digits=10, decimal_places=2, null=True, blank=True)
    photo = models.FileField('電表照片', upload_to=rental_upload_to, validators=[image_upload_validator, validate_upload_size], blank=True)
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name='填寫者', null=True, blank=True, on_delete=models.SET_NULL)
    updated_at = models.DateTimeField('更新時間', auto_now=True)

    class Meta:
        verbose_name = '電表抄表'
        verbose_name_plural = '電表抄表'

    def clean(self):
        if self.current_reading is not None and self.previous_reading is not None and self.current_reading < self.previous_reading:
            raise ValidationError('本次度數不可小於前次度數。')


class BillPayment(models.Model):
    class Method(models.TextChoices):
        TRANSFER = 'transfer', '銀行匯款'
        CASH = 'cash', '現金支付'

    bill = models.OneToOneField(Bill, verbose_name='帳單', on_delete=models.CASCADE, related_name='payment')
    method = models.CharField('付款方式', max_length=16, choices=Method.choices)
    receipt = models.FileField('匯款憑證', upload_to=rental_upload_to, validators=[upload_validator, validate_upload_size], blank=True)
    submitted_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name='付款人', on_delete=models.PROTECT, related_name='submitted_rental_payments')
    submitted_at = models.DateTimeField('付款提交時間', auto_now_add=True)
    confirmed_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name='收款確認者', null=True, blank=True, on_delete=models.PROTECT, related_name='confirmed_rental_payments')
    confirmed_at = models.DateTimeField('收款確認時間', null=True, blank=True)
    note = models.TextField('付款備註', blank=True)

    class Meta:
        verbose_name = '帳單付款'
        verbose_name_plural = '帳單付款'

    def clean(self):
        if self.method == self.Method.TRANSFER and not self.receipt:
            raise ValidationError('銀行匯款必須上傳匯款憑證。')


class BillSnapshot(models.Model):
    bill = models.ForeignKey(Bill, verbose_name='帳單', on_delete=models.CASCADE, related_name='snapshots')
    event_type = models.CharField('流程事件', max_length=64)
    payload = models.JSONField('帳單快照', default=dict)
    note = models.TextField('備註', blank=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name='操作會員', null=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField('建立時間', auto_now_add=True)

    class Meta:
        verbose_name = '帳單快照'
        verbose_name_plural = '帳單快照'
        ordering = ['-created_at']


class MaintenanceRequest(models.Model):
    class Status(models.TextChoices):
        OPEN = 'open', '待處理'
        IN_PROGRESS = 'in_progress', '處理中'
        COMPLETED = 'completed', '已完成'
        CLOSED = 'closed', '已關閉'

    unit = models.ForeignKey(Unit, verbose_name='房間', on_delete=models.PROTECT, related_name='maintenance_requests')
    lease = models.ForeignKey(Lease, verbose_name='租約', null=True, blank=True, on_delete=models.SET_NULL, related_name='maintenance_requests')
    title = models.CharField('報修主旨', max_length=160)
    description = models.TextField('問題說明')
    status = models.CharField('進度', max_length=16, choices=Status.choices, default=Status.OPEN)
    assigned_to = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name='處理人員', null=True, blank=True, on_delete=models.SET_NULL, related_name='assigned_maintenance_requests')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name='提報人', on_delete=models.PROTECT, related_name='created_maintenance_requests')
    completion_note = models.TextField('完成紀錄', blank=True)
    completed_at = models.DateTimeField('完成時間', null=True, blank=True)
    created_at = models.DateTimeField('建立時間', auto_now_add=True)
    updated_at = models.DateTimeField('更新時間', auto_now=True)

    class Meta:
        verbose_name = '維修報修'
        verbose_name_plural = '維修報修'
        ordering = ['-created_at']


class MaintenanceAttachment(models.Model):
    request = models.ForeignKey(MaintenanceRequest, verbose_name='報修單', on_delete=models.CASCADE, related_name='attachments')
    file = models.FileField('照片或附件', upload_to=rental_upload_to, validators=[upload_validator, validate_upload_size])
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name='上傳者', null=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField('上傳時間', auto_now_add=True)

    class Meta:
        verbose_name = '報修附件'
        verbose_name_plural = '報修附件'


class Announcement(models.Model):
    property = models.ForeignKey(Property, verbose_name='指定物件', null=True, blank=True, on_delete=models.CASCADE, related_name='announcements')
    title = models.CharField('公告標題', max_length=160)
    content = models.TextField('公告內容')
    published_at = models.DateTimeField('發布時間', default=timezone.now)
    expires_at = models.DateTimeField('下架時間', null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name='發布者', on_delete=models.PROTECT, related_name='rental_announcements')
    created_at = models.DateTimeField('建立時間', auto_now_add=True)

    class Meta:
        verbose_name = '公告'
        verbose_name_plural = '公告'
        ordering = ['-published_at']
