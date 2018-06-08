<?php
namespace Emipro\Apichange\Model\Order;
class InvoiceRepository extends \Magento\Sales\Model\Order\InvoiceRepository
{
    /**
     * Perform persist operations for one entity
     *
     * @param \Magento\Sales\Api\Data\InvoiceInterface $entity
     * @return \Magento\Sales\Api\Data\InvoiceInterface
     */
    public function save(\Magento\Sales\Api\Data\InvoiceInterface $entity)
    {
		$objectManager = \Magento\Framework\App\ObjectManager::getInstance();
		 
		$qtys=array();
		foreach($entity->getItems() as $_item)
		{
			$qtys[$_item->getOrderItemId()]=$_item->getQty();
		}
		
		$invoiceItems=$entity->getItems();
		$orderId=$entity->getOrderId();
		$order = $objectManager->create('Magento\Sales\Model\Order')->load($orderId);

		if (!$order->getId()) {
			throw new \Magento\Framework\Exception\LocalizedException(__('The order no longer exists.'));
		}
		if (!$order->canInvoice()) {
			throw new \Magento\Framework\Exception\LocalizedException(
				__('The order does not allow an invoice to be created.')
			);
		}
		
		$invoice=$order->prepareInvoice($qtys);

		if (!$invoice) {
			throw new LocalizedException(__('We can\'t save the invoice right now.'));
		}

		if (!$invoice->getTotalQty()) {
			throw new \Magento\Framework\Exception\LocalizedException(
				__('You can\'t create an invoice without products.')
			);
		}
		$invoice->register();
		
		$invoice->getOrder()->setCustomerNoteNotify(!$entity->getEmailSent());
		$invoice->getOrder()->setIsInProcess(true);
		
		$transactionSave = $objectManager->create(
			'Magento\Framework\DB\Transaction'
		)->addObject(
			$invoice
		)->addObject(
			$invoice->getOrder()
		);
	   $transactionSave->save();
		//exit;
		//  $this->metadata->getMapper()->save($entity);
        $this->registry[$entity->getEntityId()] = $entity;
        
        return $this->registry[$entity->getEntityId()];
    }
}
