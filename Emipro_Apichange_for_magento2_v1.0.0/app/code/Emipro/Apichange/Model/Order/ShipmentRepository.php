<?php
namespace Emipro\Apichange\Model\Order;

use Magento\Framework\Exception\CouldNotSaveException;

class ShipmentRepository extends \Magento\Sales\Model\Order\ShipmentRepository
{
    /**
     * Performs persist operations for a specified shipment.
     *
     * @param \Magento\Sales\Api\Data\ShipmentInterface $entity
     * @return \Magento\Sales\Api\Data\ShipmentInterface
     * @throws CouldNotSaveException
     */
    public function save(\Magento\Sales\Api\Data\ShipmentInterface $entity)
    {

        try {
            $objectManager = \Magento\Framework\App\ObjectManager::getInstance();
            $shipmentItems = $entity->getItems();
            $orderId = $entity->getOrderId();
            $_shipmentItems = array();
            foreach ($shipmentItems as $_item) {
                $_item_id = $_item->getOrderItemId();
                $_item_qty = $_item->getQty();
                if ($_item_id && $_item_qty) {
                    $_shipmentItems['items'][$_item_id] = $_item_qty;
                }
            }
            $shipmentItems = $_shipmentItems;
            $order = $objectManager->create('Magento\Sales\Model\Order')->load($orderId);
            if (!$order->canShip()) {
                $shipmentCollection = $order->getShipmentsCollection();
                foreach ($shipmentCollection as $shipment) {
                    $shipmentIncrementId = $shipment;
                }
                return $shipmentIncrementId;
            }

            $shipmentLoader = $objectManager->create('Magento\Shipping\Controller\Adminhtml\Order\ShipmentLoader');

            $shipmentLoader->setOrderId($orderId);
            $shipmentLoader->setShipmentId($entity->getShipmentId());
            $shipmentLoader->setShipment($shipmentItems);
            $shipment = $shipmentLoader->load();

            $shipment->register();
            $shipment->setCustomerNoteNotify(1);
            $shipment->getOrder()->setIsInProcess(true);
            $transaction = $objectManager->create(
                'Magento\Framework\DB\Transaction'
            );

            $transaction->addObject(
                $shipment
            )->addObject(
                $shipment->getOrder()
            )->save();
            $shipmentSender = $objectManager->create('\Magento\Sales\Model\Order\Email\Sender\ShipmentSender');

            /*
             * Commented becuase /rest/V1/shipment/{id}/emails/" api called for send tracking and shippment email
             * so now not send mannualy email of shippment
             */
            $this->registry[$entity->getEntityId()] = $entity;
        } catch (\Exception $e) {
            throw new CouldNotSaveException(__('Could not save shipment'), $e);
        }
        $order = $objectManager->create('Magento\Sales\Model\Order')->load($orderId);
        $shipmentCollection = $order->getShipmentsCollection();
        $trackData = $entity->getTracks();
        foreach ($trackData as $value) {
            $TrackNumber = $value->getTrackNumber();
            $CarrierCode = $value->getCarrierCode();
            $Title = $value->getTitle();
            $track = $objectManager->create('Magento\Sales\Model\Order\Shipment\Track')
                ->setParentId($shipment->getId())
                ->setTitle($Title)
                ->setNumber($TrackNumber)
                ->setCarrierCode($CarrierCode)
                ->setOrderId($orderId)
                ->save();
        }
        foreach ($shipmentCollection as $shipment) {
            $shipmentIncrementId = $shipment;
        }
        return $shipmentIncrementId;
    }
}
