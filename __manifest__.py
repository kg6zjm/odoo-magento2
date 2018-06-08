{
    # App information
    
    'name': "Odoo Magento2 Connector",   
    'version': '11.0',
    'category': 'Connector',
    'license': 'OPL-1',
    'summary' : 'Integrate & Manage all your Magento2 operations from Odoo',
    
    # Author
    'author': 'Emipro Technologies Pvt. Ltd.',
    'website': 'http://www.emiprotechnologies.com/',
    'maintainer': 'Emipro Technologies Pvt. Ltd.',
    
    # Dependencies
    'depends': ['delivery','stock','sale_management','base_sparse_field'],
    'data':[
            'security/security.xml',
            'views/logs/queue_data.xml',
            'views/logs/model_view.xml',
            'views/backend/ecommerce_data.xml',
            'views/backend/magento_model_view.xml',
            'views/backend/magento_menu.xml',
            'views/sale/sale_view.xml',
            'security/ir.model.access.csv',
            'security/rules.xml',
            'views/payment_method_view.xml',
            'views/sale/sale_workflow_process_view.xml',
            'views/partner/partner_category_view.xml',
            'views/partner/partner_view.xml',
            'views/delivery_view.xml',
            'views/account/invoice_view.xml',
            'views/product/product_category_view.xml',
            'views/product/product_view.xml',
            'views/stock/stock_view.xml',
            'views/queue_job_view.xml',
            'report/sale_report_view.xml',
            'report/invoice_report_view.xml',
            'wizard/magento_import_export_operation_view.xml',
            'wizard/res_config.xml',
            'data/magento_sequence.xml',
            'views/product/product_attribute_view.xml',
            'views/product/attribute_set_view.xml',
            'views/product/attribute_group_view.xml',
            'views/product/attribute_option_view.xml',
            'views/product/dynamic_attribute_option_view.xml',
            'views/product/product_image_view.xml',
            'wizard/export_multi_products_view.xml',
            'wizard/export_product_to_magento.xml',
            'views/backend/magento_data.xml',
            'views/sale/automatic_workflow_data.xml',
            ],

    # Odoo Store Specific
    
    'images': ['static/description/main_screen.jpg'],
    'installable': True,
    'auto_install': False,
    'application' : True,
    'price': 399.00,
    'currency': 'EUR',
    
}
