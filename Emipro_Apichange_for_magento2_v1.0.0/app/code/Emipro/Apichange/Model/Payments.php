<?php

namespace Emipro\Apichange\Model;

use Emipro\Apichange\Api\PaymentInterface;


class Payments implements PaymentInterface
{
    protected $paymentHelper;

    public function __construct(
        \Magento\Payment\Helper\Data $paymentHelper
    ) {
        $this->paymentHelper = $paymentHelper;
    }

    public function payment() {
        $objManager = \Magento\Framework\App\ObjectManager::getInstance();
        $methods = [];
        $payments = $this->paymentHelper->getPaymentMethods();
        //$payments = $objManager->create('Magento\Payment\Model\Config')->getActiveMethods();
        $paymentMethods = [];
        $scopeConfig=$objManager->create('Magento\Framework\App\Config\ScopeConfigInterface');
        $storeScope = \Magento\Store\Model\ScopeInterface::SCOPE_STORE;
        foreach ($payments as $paymentCode => $paymentModel) {
            $paymentTitles =  $scopeConfig->getValue('payment/'.$paymentCode.'/title', $storeScope);
            if($paymentTitles != ''){
                $paymentMethods[] = array('value' => $paymentCode, 'title' => $paymentTitles);
            }
        }
        return $paymentMethods;
    }
}
